const { google } = require('googleapis');
const config = require('../config');
const logger = require('../utils/logger');

class CalendarClient {
  constructor() {
    this.calendar = null;
    this.calendarId = config.google.calendarId;
    this.init();
  }

  init() {
    if (config.google.serviceAccountJson) {
      try {
        const credentials = JSON.parse(config.google.serviceAccountJson);
        const auth = new google.auth.GoogleAuth({
          credentials,
          scopes: ['https://www.googleapis.com/auth/calendar'],
        });

        this.calendar = google.calendar({ version: 'v3', auth });
        logger.info('Google Calendar initialized');
      } catch (error) {
        logger.error('Failed to initialize Calendar:', error.message);
      }
    }
  }

  isConfigured() {
    return !!this.calendar;
  }

  async listEvents(timeMin = new Date(), timeMax = null, maxResults = 10) {
    if (!this.isConfigured()) {
      logger.warn('Google Calendar not configured');
      return [];
    }

    try {
      const params = {
        calendarId: this.calendarId,
        timeMin: timeMin.toISOString(),
        maxResults,
        singleEvents: true,
        orderBy: 'startTime',
      };

      if (timeMax) {
        params.timeMax = timeMax.toISOString();
      }

      const response = await this.calendar.events.list(params);
      return response.data.items || [];

    } catch (error) {
      logger.error('Calendar list error:', error.message);
      throw new Error('Failed to list calendar events');
    }
  }

  async createEvent({ summary, description, startTime, endTime, attendees = [] }) {
    if (!this.isConfigured()) {
      logger.warn('Google Calendar not configured');
      return null;
    }

    try {
      const event = {
        summary,
        description,
        start: {
          dateTime: startTime.toISOString(),
          timeZone: config.timezone,
        },
        end: {
          dateTime: endTime.toISOString(),
          timeZone: config.timezone,
        },
      };

      if (attendees.length > 0) {
        event.attendees = attendees.map(email => ({ email }));
      }

      const response = await this.calendar.events.insert({
        calendarId: this.calendarId,
        resource: event,
        sendUpdates: attendees.length > 0 ? 'all' : 'none',
      });

      logger.info(`Calendar event created: ${response.data.id}`);
      return response.data;

    } catch (error) {
      logger.error('Calendar create error:', error.message);
      throw new Error('Failed to create calendar event');
    }
  }

  async findAvailableSlots(date, durationMinutes = 60) {
    if (!this.isConfigured()) {
      return [];
    }

    try {
      const startOfDay = new Date(date);
      startOfDay.setHours(9, 0, 0, 0);

      const endOfDay = new Date(date);
      endOfDay.setHours(18, 0, 0, 0);

      const events = await this.listEvents(startOfDay, endOfDay, 50);

      const slots = [];
      let currentTime = new Date(startOfDay);

      for (const event of events) {
        const eventStart = new Date(event.start.dateTime || event.start.date);
        const eventEnd = new Date(event.end.dateTime || event.end.date);

        while (currentTime < eventStart) {
          const slotEnd = new Date(currentTime.getTime() + durationMinutes * 60000);
          if (slotEnd <= eventStart) {
            slots.push({
              start: new Date(currentTime),
              end: slotEnd,
            });
          }
          currentTime = new Date(currentTime.getTime() + 30 * 60000);
        }

        currentTime = eventEnd > currentTime ? eventEnd : currentTime;
      }

      while (currentTime < endOfDay) {
        const slotEnd = new Date(currentTime.getTime() + durationMinutes * 60000);
        if (slotEnd <= endOfDay) {
          slots.push({
            start: new Date(currentTime),
            end: slotEnd,
          });
        }
        currentTime = new Date(currentTime.getTime() + 30 * 60000);
      }

      return slots.slice(0, 5);

    } catch (error) {
      logger.error('Calendar slots error:', error.message);
      return [];
    }
  }

  async deleteEvent(eventId) {
    if (!this.isConfigured()) {
      return false;
    }

    try {
      await this.calendar.events.delete({
        calendarId: this.calendarId,
        eventId,
      });

      logger.info(`Calendar event deleted: ${eventId}`);
      return true;

    } catch (error) {
      logger.error('Calendar delete error:', error.message);
      return false;
    }
  }
}

module.exports = new CalendarClient();
