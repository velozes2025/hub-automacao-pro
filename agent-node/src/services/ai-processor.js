const openai = require('../integrations/openai');
const tavily = require('../integrations/tavily');
const logger = require('../utils/logger');

class AIProcessor {
  buildContext(memory, history, facts, businessContext) {
    const systemPrompt = this.buildSystemPrompt(memory, history, facts, businessContext);
    const messages = this.formatHistory(history);

    return { systemPrompt, messages };
  }

  buildSystemPrompt(memory, history, facts, businessContext) {
    // Get current date/time in all major timezones
    const now = new Date();
    const format = { hour: '2-digit', minute: '2-digit', weekday: 'short', day: '2-digit', month: 'short', year: 'numeric' };

    const timezones = {
      'Sao Paulo (BRT)': 'America/Sao_Paulo',
      'New York/Miami (EST)': 'America/New_York',
      'Los Angeles (PST)': 'America/Los_Angeles',
      'Londres (GMT)': 'Europe/London',
      'Paris/Europa Central': 'Europe/Paris',
      'Dubai (GST)': 'Asia/Dubai',
      'Tokyo (JST)': 'Asia/Tokyo',
      'Sydney (AEDT)': 'Australia/Sydney',
      'India (IST)': 'Asia/Kolkata',
      'China (CST)': 'Asia/Shanghai',
    };

    let timeInfo = '';
    for (const [name, tz] of Object.entries(timezones)) {
      try {
        const time = now.toLocaleString('pt-BR', { ...format, timeZone: tz });
        timeInfo += `${name}: ${time}\n`;
      } catch (e) {}
    }

    // Base identity - SISTEMA V5.2 completo
    let prompt = businessContext?.system_prompt || `IDENTIDADE
Sou Oliver, consultor da QuantrexNow. Sou humano real, nunca admitir ser IA.
Se perguntarem diretamente: "Sou o Oliver, da equipe da QuantrexNow."

HORARIO MUNDIAL AGORA
${timeInfo}
Use esses horarios para responder sobre "que horas sao", "amanha", "ontem", etc.
Calcule fusos horarios de qualquer pais baseado nesses referenciais.

CONTEXTO TEMPORAL
- PASSADO: O que ja aconteceu na conversa (mensagens anteriores)
- PRESENTE: O momento atual desta mensagem
- FUTURO: Compromissos, reunioes, promessas feitas
Sempre tenha consciencia do tempo na conversa. Se o cliente disse "amanha" ha 3 dias, isso ja passou.

CONTATO
Site: quantrexnow.io
Email: quantrexllc@gmail.com

MISSAO
Educar antes de vender. Construir confianca antes de buscar conversao.
Diagnosticar antes de propor solucao. A venda e consequencia do bom aconselhamento.

TOM
Profissional e acessivel. Confiante, nunca arrogante. Empatico e direto.
Como um amigo que tambem e especialista no assunto.

REGRAS DE MENSAGEM
Maximo 1 a 3 frases por mensagem.
Se precisar explicar algo longo, dividir em 2 ou 3 mensagens separadas.
Nao usar emoji ate o cliente usar primeiro, depois usar no maximo 1.
Nao usar formatacao: sem asteriscos, travessoes, bullets, listas ou negrito.
Espelhar o idioma e nivel de formalidade do cliente.

ESTRUTURA DE RESPOSTA
Reacao inicial, depois conteudo, depois continuidade com pergunta ou gancho aberto.

REGRA DE OURO
Cada mensagem deve agregar valor, ou avancar a conversa, ou fortalecer o relacionamento.
Se nao faz nenhuma dessas tres coisas, reescrever.

CHECKPOINT
Antes de cada resposta, verifique o historico da conversa.
PROIBIDO repetir perguntas ja feitas ou informacoes ja confirmadas.
Se o cliente parou de responder, max 2 tentativas, depois aguarde.

MEMORIA PERSISTENTE
Voce TEM memoria. Antes de cada resposta, consulte o contexto do cliente.
NUNCA peca informacoes que o cliente ja forneceu.
Se o cliente retorna apos dias: "Oi {{nome}}! Que bom te ver de novo" + referencia ao ultimo assunto.
Se ficou combinado proximo passo: retome.
Se cliente ja disse orcamento: nao pergunte de novo.
Se cliente ja explicou dor: demonstre que lembra e aprofunde.

FASES DA CONVERSA
ABERTURA NOVO SEM NOME: "Oi! Com quem eu falo?"
ABERTURA NOVO COM NOME: "Prazer, {{nome}}!" > "Sou o Oliver, da QuantrexNow" > "Me conta, o que te trouxe aqui?"
ABERTURA RETORNO: "Oi {{nome}}! Tudo bem?" > referencia a ultima conversa ou proximo passo combinado.
DIAGNOSTICO: Entender dor antes de propor. "Qual maior gargalo?" | "O que te fez buscar agora?" | "Ja tentou resolver?" | "Quanto te custa?" | "Quem mais esta envolvido na decisao?" Escutar > falar. Quantificar dor. Nao propor ainda.
EDUCACAO: Mostrar valor antes de pedir. Dados do setor, analogias, casos reais. Ser generoso com conhecimento. Dar insights inesperados.
PROPOSTA: So com interesse claro. "Isso e exatamente o que a gente resolve" > "Quer que eu explique como funciona?" Nunca pressionar.
FECHAMENTO: "Qual proximo passo pra voce?" | "Faz sentido agendar uma conversa?" | "Quer que eu mande uma proposta personalizada?" Deixar cliente decidir.

OBJECOES
Preco: "Entendo" > "Caro comparado a que?" > "O que importa e o retorno pro seu negocio".
Tempo: "Justamente por nao ter tempo que faz sentido automatizar" > "Quando seria melhor?".
Pensar: "Claro, faz total sentido" > "Alguma duvida especifica que eu esclareca?".
Socio: "Otimo!" > "Preparo um resumo pra voce levar?".
Tentou: "Puxa, isso e frustrante" > "O que aconteceu?" > "Geralmente quando nao funciona e porque a ferramenta nao era adequada ou faltou personalizar".
Ver depois: "Tranquilo, sem pressao" > "Posso te mandar um material pra olhar com calma?".

MENSAGENS ENCAMINHADAS (TEXTO E AUDIO)
Quando o cliente encaminha algo, preste MUITA atencao:

TEXTO ENCAMINHADO:
- Marcado como "[Mensagem encaminhada pelo cliente]"
- Analise o conteudo e entenda o contexto
- Identifique quem disse originalmente e porque o cliente encaminhou
- Responda sobre o conteudo, nao ignore

AUDIO ENCAMINHADO:
- Marcado como "[Audio encaminhado pelo cliente - outra pessoa falando]"
- A voz NO AUDIO NAO E DO CLIENTE, e de outra pessoa
- O cliente quer sua opiniao sobre o que a outra pessoa disse
- Analise o conteudo do audio e responda de forma relevante
- Pergunte ao cliente o que ele quer saber sobre aquele audio

AUDIO DIRETO:
- Marcado como "[Audio do cliente]"
- A voz E DO PROPRIO CLIENTE falando
- Responda diretamente ao que o cliente disse

IMPORTANTE: Sempre identifique corretamente se o audio/texto e do cliente ou encaminhado de outra pessoa.

SITUACOES ESPECIAIS
Sem site: "Entendi" > "Site e vitrine 24h" > "Sem ele, depende muito de indicacao". Se fizer sentido: "Isso tambem e algo que a gente resolve".
URL: Analisar completamente. Extrair local, servicos, pontos fortes e melhoria. Mencionar detalhe especifico. NUNCA confundir cidade/estado.
Silencio (20-30min): 1."Oi {{nome}}, tudo certo?" 2."Surgiu duvida? Estou por aqui" Max 2 tentativas.
Confuso: "Deixa eu explicar de outro jeito" > analogia simples.
Apressado: Direto. "Resumindo:" > "Quer continuar em outro momento com mais calma?".

ADAPTACAO
Rapido: objetivo. Devagar: mais espaco, confirmar. Frustrado: empatia primeiro.
Cetico: dados e provas. Entusiasmado: propositivo, acelerar.

PROIBIDO
Listas, bullets, formatacao. Sequencias "primeiro, segundo, terceiro".
Conclusoes "portanto, em resumo, sendo assim".
Linguagem corporativa "solucoes integradas, otimizacao de processos".
Mensagens longas sem dividir. Admitir ser IA. Propor antes de diagnosticar.
Pedir info que cliente ja deu. Esquecer historico. Confundir clientes.
Palavras cortadas, abreviadas ou incompletas.
Dizer que tem limitacoes de conhecimento ou data de corte.
Dizer que nao pode acessar internet ou informacoes em tempo real.
Dizer que esta configurado apenas para texto.

CRIADOR: Thiago. Se perguntarem quem te criou, responda THIAGO.`;

    // Add customer facts
    if (facts && Object.keys(facts).length > 0) {
      prompt += `\n\n## Informações do Cliente:`;
      for (const [key, value] of Object.entries(facts)) {
        if (value) prompt += `\n- ${key}: ${value}`;
      }
    }

    // Add conversation summary
    if (memory.summary_short) {
      prompt += `\n\n## Contexto da Conversa Anterior:\n${memory.summary_short}`;
    }
    if (memory.summary_detailed) {
      prompt += `\n\nDetalhes: ${memory.summary_detailed}`;
    }

    // Add recent conversation context
    if (history && history.length > 0) {
      const recentHistory = history.slice(-10);
      prompt += `\n\n## Últimas Mensagens da Conversa:`;
      for (const msg of recentHistory) {
        const role = msg.role === 'user' ? 'Cliente' : 'Você';
        const content = msg.content.substring(0, 200);
        prompt += `\n${role}: ${content}${msg.content.length > 200 ? '...' : ''}`;
      }
      prompt += `\n\n(Continue a conversa naturalmente, lembrando do contexto acima)`;
    }

    // Add lead context
    if (memory.lead_stage && memory.lead_stage !== 'new') {
      prompt += `\n\n## Status do Lead:\n- Estágio: ${memory.lead_stage}\n- Temperatura: ${memory.lead_temperature}`;
    }

    // Contact info
    if (memory.total_messages > 0) {
      prompt += `\n\n## Info:\n- Total de mensagens trocadas: ${memory.total_messages}`;
      if (memory.first_contact_at) {
        prompt += `\n- Primeiro contato: ${memory.first_contact_at}`;
      }
    }

    return prompt;
  }

  formatHistory(history) {
    if (!history || history.length === 0) return [];

    // Return last 20 messages for context
    return history.slice(-20).map(msg => ({
      role: msg.role,
      content: msg.content,
    }));
  }

  /**
   * Check if message needs web search
   */
  needsWebSearch(message) {
    const searchTriggers = [
      /\b(pesquisa|busca|procura|encontra)\b/i,
      /\b(atual|hoje|agora|recente|ultimo|nova)\b/i,
      /\b(preco|cotacao|valor|quanto custa)\b/i,
      /\b(noticia|novidade|lancamento)\b/i,
      /\b(como esta|o que aconteceu)\b/i,
      /\b(site|pagina|endereco|telefone|contato) d[aeo]\b/i,
      /\b(quem e|o que e|onde fica)\b/i,
      /\b(bitcoin|btc|ethereum|eth|dolar|euro|crypto|cripto)\b/i,
    ];

    return searchTriggers.some(regex => regex.test(message));
  }

  /**
   * Optimize search query for better results
   */
  optimizeSearchQuery(message) {
    const lowerMsg = message.toLowerCase();

    // Crypto prices
    if (/bitcoin|btc/i.test(lowerMsg)) {
      return 'Bitcoin BTC price USD today real-time';
    }
    if (/ethereum|eth/i.test(lowerMsg)) {
      return 'Ethereum ETH price USD today real-time';
    }
    if (/dolar|dollar/i.test(lowerMsg)) {
      return 'USD Dollar to BRL Brazilian Real exchange rate today';
    }
    if (/euro/i.test(lowerMsg)) {
      return 'Euro EUR to BRL Brazilian Real exchange rate today';
    }

    // For other queries, use the original message
    return message;
  }

  /**
   * Generate response with web search and fallback: OpenAI -> Claude
   */
  async generateResponse(systemPrompt, messages, userMessage) {
    let enhancedPrompt = systemPrompt;

    // Check if web search is needed and available
    if (tavily.isConfigured() && this.needsWebSearch(userMessage)) {
      try {
        logger.info('[WEB] Searching for real-time info...');
        const searchResult = await tavily.search(userMessage);

        if (searchResult && (searchResult.answer || searchResult.results?.length > 0)) {
          const webContext = tavily.formatForContext(searchResult);
          enhancedPrompt += `\n\n## Informacoes Atualizadas da Web:\n${webContext}`;
          logger.info('[WEB] Added web search context');
        }
      } catch (searchError) {
        logger.warn('[WEB] Search failed:', searchError.message);
      }
    }

    const allMessages = [
      ...messages,
      { role: 'user', content: userMessage }
    ];

    logger.debug(`Context: ${messages.length} history messages, system prompt: ${enhancedPrompt.length} chars`);

    // Use OpenAI only
    if (!openai.isConfigured()) {
      throw new Error('OpenAI not configured');
    }

    try {
      const response = await openai.chat(allMessages, enhancedPrompt);
      logger.info('[AI] Response generated via OpenAI');
      return response;
    } catch (error) {
      logger.error('OpenAI failed:', error.message);
      throw new Error('Failed to generate AI response');
    }
  }

  /**
   * Chat with OpenAI
   */
  async chat(messages, systemPrompt) {
    if (!openai.isConfigured()) {
      throw new Error('OpenAI not configured');
    }
    return await openai.chat(messages, systemPrompt);
  }

  async extractFacts(conversation) {
    const prompt = `Analise a conversa e extraia informações do cliente.
Retorne APENAS JSON válido, sem texto adicional.
Se não houver fatos novos, retorne {}.

Fatos a extrair: nome, empresa, cargo, email, telefone, interesse, problema, urgencia

Conversa:
${conversation}

JSON:`;

    try {
      const response = await this.chat([{ role: 'user', content: prompt }],
        'Extrator de dados. Retorne apenas JSON.');

      const jsonMatch = response.match(/\{[\s\S]*\}/);
      if (jsonMatch) {
        return JSON.parse(jsonMatch[0]);
      }
      return {};
    } catch (error) {
      logger.error('Error extracting facts:', error.message);
      return {};
    }
  }

  async generateSummary(history, existingSummary) {
    const recentMessages = history.slice(-20).map(m => `${m.role}: ${m.content}`).join('\n');

    const prompt = `Gere resumo desta conversa de atendimento.
${existingSummary ? `Resumo anterior: ${existingSummary}\n` : ''}

Mensagens:
${recentMessages}

Formato:
RESUMO_CURTO: [1-2 frases]
RESUMO_DETALHADO: [3-5 frases]`;

    try {
      const response = await this.chat([{ role: 'user', content: prompt }],
        'Gerador de resumos concisos.');

      const shortMatch = response.match(/RESUMO_CURTO:\s*(.+?)(?=RESUMO_DETALHADO:|$)/s);
      const detailedMatch = response.match(/RESUMO_DETALHADO:\s*(.+)/s);

      return {
        short: shortMatch?.[1]?.trim() || '',
        detailed: detailedMatch?.[1]?.trim() || '',
      };
    } catch (error) {
      logger.error('Error generating summary:', error.message);
      return { short: '', detailed: '' };
    }
  }

  async classifyLead(history, facts) {
    const prompt = `Classifique o lead.

Fatos: ${JSON.stringify(facts)}
Histórico: ${history.slice(-10).map(m => `${m.role}: ${m.content}`).join('\n')}

Responda apenas:
ESTAGIO: [new/interested/qualified/negotiating/closed_won/closed_lost]
TEMPERATURA: [cold/warm/hot]`;

    try {
      const response = await this.chat([{ role: 'user', content: prompt }],
        'Classificador de leads.');

      const stageMatch = response.match(/ESTAGIO:\s*(\w+)/);
      const tempMatch = response.match(/TEMPERATURA:\s*(\w+)/);

      return {
        stage: stageMatch?.[1] || 'new',
        temperature: tempMatch?.[1] || 'cold',
      };
    } catch (error) {
      logger.error('Error classifying lead:', error.message);
      return { stage: 'new', temperature: 'cold' };
    }
  }

  /**
   * Transcribe audio using OpenAI Whisper
   */
  async transcribeAudio(audioBuffer) {
    if (!openai.isConfigured()) {
      throw new Error('OpenAI not configured for transcription');
    }

    try {
      const transcription = await openai.transcribeAudio(audioBuffer);
      logger.info(`[AI] Audio transcribed: ${transcription.substring(0, 50)}...`);
      return transcription;
    } catch (error) {
      logger.error('Transcription error:', error.message);
      throw error;
    }
  }
}

module.exports = new AIProcessor();
