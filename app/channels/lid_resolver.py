"""LID (List ID) resolution — 7 strategies, scoped per WhatsApp account.

Resolves WhatsApp LID JIDs (e.g., 12345@lid) to real phone numbers.
All caching and DB lookups are scoped by whatsapp_account_id to prevent
cross-tenant data leaks.

Strategies (in order):
1. Memory cache (scoped by account_id + lid_jid)
2. DB mapping table
3. Contacts API profilePicUrl match
4. Contacts API pushName match (unique only)
5. Evolution DB Contact table (profilePicUrl)
6. Evolution DB Contact table (pushName)
7. Message timestamp correlation
"""

import logging
from app.channels import whatsapp
from app.db import lid as lid_db

log = logging.getLogger('channels.lid_resolver')

# In-memory cache: (whatsapp_account_id, lid_jid) -> phone
_cache = {}


def _same_profile_pic(url1, url2):
    if not url1 or not url2:
        return False
    return url1.split('?')[0] == url2.split('?')[0]


def _save(account_id, lid_jid, phone, instance_name, push_name, source):
    """Save resolved mapping to cache + DB. Respects source priority."""
    result = lid_db.save_mapping(account_id, lid_jid, phone, source, push_name)
    if result is None:
        # Blocked by priority — don't update cache either
        log.info(f'LID save skipped (low priority {source}): {lid_jid} -/-> {phone}')
        return False
    _cache[(str(account_id), lid_jid)] = phone
    log.info(f'LID resolved via {source}: {lid_jid} -> {phone}')
    return True


def resolve(whatsapp_account_id, instance_name, lid_jid):
    """Resolve a LID JID to a real phone number using 7 strategies.

    Returns phone string or None if unresolvable.
    """
    account_id = str(whatsapp_account_id)
    cache_key = (account_id, lid_jid)

    # Strategy 1: Memory cache (validated against DB to catch manual corrections)
    if cache_key in _cache:
        cached_phone = _cache[cache_key]
        try:
            db_phone = lid_db.get_phone(account_id, lid_jid)
            if db_phone and db_phone != cached_phone:
                log.warning(
                    f'Cache STALE for {lid_jid}: cache={cached_phone}, DB={db_phone}. Using DB.'
                )
                _cache[cache_key] = db_phone
                return db_phone
        except Exception:
            pass
        return cached_phone

    # Strategy 2: DB mapping
    try:
        db_phone = lid_db.get_phone(account_id, lid_jid)
        if db_phone:
            _cache[cache_key] = db_phone
            log.info(f'LID resolved via DB: {lid_jid} -> {db_phone}')
            return db_phone
    except Exception:
        pass

    # Strategies 3+4: Contacts API
    push_name = ''
    try:
        contacts = whatsapp.fetch_all_contacts(instance_name)
        if contacts:
            lid_contact = None
            for c in contacts:
                if c.get('remoteJid') == lid_jid:
                    lid_contact = c
                    break

            if lid_contact:
                pic_url = lid_contact.get('profilePicUrl')
                push_name = lid_contact.get('pushName', '')

                # Strategy 3: profilePicUrl match
                if pic_url:
                    for c in contacts:
                        rjid = c.get('remoteJid', '')
                        if (rjid.endswith('@s.whatsapp.net')
                                and _same_profile_pic(c.get('profilePicUrl'), pic_url)):
                            phone = rjid.split('@')[0]
                            _save(account_id, lid_jid, phone, instance_name, push_name, 'profilePic API')
                            return phone

                # Strategy 4: pushName (unique match only)
                if push_name:
                    candidates = [
                        c for c in contacts
                        if c.get('remoteJid', '').endswith('@s.whatsapp.net')
                        and c.get('pushName') == push_name
                    ]
                    if len(candidates) == 1:
                        phone = candidates[0]['remoteJid'].split('@')[0]
                        _save(account_id, lid_jid, phone, instance_name, push_name, 'pushName API')
                        return phone
    except Exception:
        pass

    # Strategies 5+6: Evolution DB Contact table
    try:
        phone = lid_db.resolve_via_evolution_db_contact(lid_jid)
        if phone:
            _save(account_id, lid_jid, phone, instance_name, push_name, 'Evolution DB Contact')
            return phone
    except Exception:
        pass

    # Strategy 7: Message timestamp correlation
    try:
        phone = lid_db.resolve_via_message_correlation(lid_jid)
        if phone:
            _save(account_id, lid_jid, phone, instance_name, push_name, 'msg correlation')
            return phone
    except Exception:
        pass

    log.warning(f'LID unresolved (7 strategies): {lid_jid} (push={push_name})')
    return None


def learn_from_sent_message(whatsapp_account_id, instance_name, data):
    """Learn LID-phone mapping from an outgoing message."""
    account_id = str(whatsapp_account_id)
    try:
        remote_jid = data.get('key', {}).get('remoteJid', '')
        if '@s.whatsapp.net' not in remote_jid:
            return
        phone = remote_jid.split('@')[0]
        push_name = data.get('pushName', '')

        contacts = whatsapp.fetch_all_contacts(instance_name)
        if not contacts:
            return

        sent_contact = None
        for c in contacts:
            if c.get('remoteJid') == remote_jid:
                sent_contact = c
                break
        if not sent_contact:
            return

        pic = sent_contact.get('profilePicUrl')
        pn = sent_contact.get('pushName', '') or push_name

        if pic:
            for c in contacts:
                rjid = c.get('remoteJid', '')
                if '@lid' in rjid and _same_profile_pic(c.get('profilePicUrl'), pic):
                    _save(account_id, rjid, phone, instance_name, pn or c.get('pushName', ''), 'sent profilePic')
                    return

        if pn:
            lid_candidates = [
                c for c in contacts
                if '@lid' in c.get('remoteJid', '') and c.get('pushName') == pn
            ]
            if len(lid_candidates) == 1:
                rjid = lid_candidates[0]['remoteJid']
                if (account_id, rjid) not in _cache:
                    _save(account_id, rjid, phone, instance_name, pn, 'sent pushName')
    except Exception:
        pass


def learn_from_contacts_event(whatsapp_account_id, instance_name, data):
    """Learn LID-phone mapping from contacts.upsert/update events."""
    account_id = str(whatsapp_account_id)
    try:
        contacts = data if isinstance(data, list) else [data]
        for contact in contacts:
            if not isinstance(contact, dict):
                continue
            contact_id = contact.get('id', '') or contact.get('remoteJid', '')
            lid = contact.get('lid', '')
            push_name = (
                contact.get('name')
                or contact.get('notify', '')
                or contact.get('pushName', '')
            )
            if (contact_id and '@s.whatsapp.net' in contact_id
                    and lid and '@lid' in lid):
                phone = contact_id.split('@')[0]
                _save(account_id, lid, phone, instance_name, push_name, 'contacts event')
                return lid, phone
    except Exception:
        pass
    return None, None
