const nodemailer = require('nodemailer');
const config = require('../config');
const logger = require('../utils/logger');

class GmailClient {
  constructor() {
    this.transporter = null;
    this.init();
  }

  init() {
    if (config.gmail.user && config.gmail.appPassword) {
      this.transporter = nodemailer.createTransport({
        service: 'gmail',
        auth: {
          user: config.gmail.user,
          pass: config.gmail.appPassword,
        },
      });
      logger.info('Gmail transporter initialized');
    }
  }

  isConfigured() {
    return !!this.transporter;
  }

  async sendEmail({ to, subject, text, html }) {
    if (!this.isConfigured()) {
      logger.warn('Gmail not configured');
      return null;
    }

    try {
      const mailOptions = {
        from: config.gmail.user,
        to,
        subject,
        text,
        html,
      };

      const info = await this.transporter.sendMail(mailOptions);
      logger.debug(`Email sent: ${info.messageId}`);
      return info;

    } catch (error) {
      logger.error('Gmail error:', error);
      throw new Error('Failed to send email');
    }
  }

  async sendLeadNotification(leadData) {
    const subject = `Novo Lead: ${leadData.nome || leadData.whatsappId}`;
    const html = `
      <h2>Novo Lead Capturado</h2>
      <ul>
        <li><strong>WhatsApp:</strong> ${leadData.whatsappId}</li>
        ${leadData.nome ? `<li><strong>Nome:</strong> ${leadData.nome}</li>` : ''}
        ${leadData.empresa ? `<li><strong>Empresa:</strong> ${leadData.empresa}</li>` : ''}
        ${leadData.interesse ? `<li><strong>Interesse:</strong> ${leadData.interesse}</li>` : ''}
        <li><strong>Estágio:</strong> ${leadData.stage || 'new'}</li>
        <li><strong>Temperatura:</strong> ${leadData.temperature || 'cold'}</li>
      </ul>
      <p><em>Gerado automaticamente pelo Hub de Automação</em></p>
    `;

    return this.sendEmail({
      to: config.gmail.user,
      subject,
      text: `Novo lead: ${leadData.whatsappId}`,
      html,
    });
  }
}

module.exports = new GmailClient();
