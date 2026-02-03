const axios = require('axios');
const config = require('../config');
const logger = require('../utils/logger');

class AirtableClient {
  constructor() {
    this.apiKey = config.airtable.apiKey;
    this.baseId = config.airtable.baseId;
    this.baseUrl = 'https://api.airtable.com/v0';
  }

  isConfigured() {
    return !!(this.apiKey && this.baseId);
  }

  getHeaders() {
    return {
      'Authorization': `Bearer ${this.apiKey}`,
      'Content-Type': 'application/json',
    };
  }

  async createRecord(tableName, fields) {
    if (!this.isConfigured()) {
      logger.warn('Airtable not configured');
      return null;
    }

    try {
      const url = `${this.baseUrl}/${this.baseId}/${tableName}`;
      const response = await axios.post(url, {
        fields: fields,
      }, {
        headers: this.getHeaders(),
      });

      logger.debug(`Airtable record created in ${tableName}`);
      return response.data;

    } catch (error) {
      logger.error('Airtable API error:', error.response?.data || error.message);
      throw new Error('Failed to create Airtable record');
    }
  }

  async updateRecord(tableName, recordId, fields) {
    if (!this.isConfigured()) {
      logger.warn('Airtable not configured');
      return null;
    }

    try {
      const url = `${this.baseUrl}/${this.baseId}/${tableName}/${recordId}`;
      const response = await axios.patch(url, {
        fields: fields,
      }, {
        headers: this.getHeaders(),
      });

      logger.debug(`Airtable record ${recordId} updated`);
      return response.data;

    } catch (error) {
      logger.error('Airtable API error:', error.response?.data || error.message);
      throw new Error('Failed to update Airtable record');
    }
  }

  async findRecords(tableName, formula = '', maxRecords = 100) {
    if (!this.isConfigured()) {
      logger.warn('Airtable not configured');
      return [];
    }

    try {
      const url = `${this.baseUrl}/${this.baseId}/${tableName}`;
      const params = { maxRecords };

      if (formula) {
        params.filterByFormula = formula;
      }

      const response = await axios.get(url, {
        headers: this.getHeaders(),
        params,
      });

      return response.data.records || [];

    } catch (error) {
      logger.error('Airtable API error:', error.response?.data || error.message);
      throw new Error('Failed to find Airtable records');
    }
  }

  async upsertLead(whatsappId, fields) {
    const existing = await this.findRecords('Leads', `{WhatsApp} = '${whatsappId}'`, 1);

    if (existing.length > 0) {
      return this.updateRecord('Leads', existing[0].id, fields);
    } else {
      return this.createRecord('Leads', { WhatsApp: whatsappId, ...fields });
    }
  }

  /**
   * Create a meeting/reunion record
   */
  async createMeeting(fields) {
    return this.createRecord('Reunioes', fields);
  }

  /**
   * Get pending meetings
   */
  async getPendingMeetings() {
    return this.findRecords('Reunioes', `{Status} = 'Pendente'`, 50);
  }

  /**
   * Get meetings for a specific date
   */
  async getMeetingsByDate(date) {
    // date format: YYYY-MM-DD
    return this.findRecords('Reunioes', `IS_SAME({Data}, '${date}', 'day')`, 50);
  }

  /**
   * Update meeting status
   */
  async updateMeetingStatus(recordId, status) {
    return this.updateRecord('Reunioes', recordId, { Status: status });
  }

  /**
   * Get upcoming meetings (next 7 days)
   */
  async getUpcomingMeetings() {
    const today = new Date().toISOString().split('T')[0];
    return this.findRecords('Reunioes',
      `AND({Status} != 'Cancelada', {Data} >= '${today}')`,
      50
    );
  }
}

module.exports = new AirtableClient();
