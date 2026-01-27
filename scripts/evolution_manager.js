#!/usr/bin/env node
/**
 * Evolution API Manager - Gerenciador de Instâncias WhatsApp
 * Hub Automação Pro (Node.js version)
 *
 * Uso:
 *   node evolution_manager.js criar <nome-instancia>
 *   node evolution_manager.js qrcode <nome-instancia>
 *   node evolution_manager.js status <nome-instancia>
 *   node evolution_manager.js listar
 *   node evolution_manager.js deletar <nome-instancia>
 */

require('dotenv').config({ path: '../.env' });

const EVOLUTION_URL = process.env.EVOLUTION_SERVER_URL || 'http://localhost:8080';
const API_KEY = process.env.EVOLUTION_API_KEY || 'sua-chave-global-evolution-aqui';

// Cores
const colors = {
    green: '\x1b[32m',
    red: '\x1b[31m',
    yellow: '\x1b[33m',
    blue: '\x1b[34m',
    cyan: '\x1b[36m',
    reset: '\x1b[0m',
    bold: '\x1b[1m'
};

const log = {
    success: (msg) => console.log(`${colors.green}✓ ${msg}${colors.reset}`),
    error: (msg) => console.log(`${colors.red}✗ ${msg}${colors.reset}`),
    info: (msg) => console.log(`${colors.blue}ℹ ${msg}${colors.reset}`),
    warning: (msg) => console.log(`${colors.yellow}⚠ ${msg}${colors.reset}`)
};

async function apiRequest(endpoint, method = 'GET', data = null) {
    const url = `${EVOLUTION_URL}${endpoint}`;

    const options = {
        method,
        headers: {
            'apikey': API_KEY,
            'Content-Type': 'application/json'
        }
    };

    if (data) {
        options.body = JSON.stringify(data);
    }

    try {
        const response = await fetch(url, options);
        const result = await response.json();

        if (!response.ok) {
            return { error: true, status: response.status, message: result };
        }

        return result;
    } catch (error) {
        return { error: true, message: error.message };
    }
}

async function criarInstancia(nome) {
    log.info(`Criando instância: ${nome}`);

    const data = {
        instanceName: nome,
        qrcode: true,
        integration: 'WHATSAPP-BAILEYS'
    };

    const result = await apiRequest('/instance/create', 'POST', data);

    if (result.error) {
        log.error(`Erro ao criar: ${JSON.stringify(result.message)}`);
        return;
    }

    log.success(`Instância '${nome}' criada com sucesso!`);

    if (result.qrcode?.base64) {
        exibirQRCode(result.qrcode.base64);
    }

    return result;
}

async function obterQRCode(nome) {
    log.info(`Obtendo QR Code da instância: ${nome}`);

    const result = await apiRequest(`/instance/connect/${nome}`);

    if (result.error) {
        log.error(`Erro: ${JSON.stringify(result.message)}`);
        return;
    }

    if (result.base64) {
        log.success('QR Code obtido! Escaneie com seu WhatsApp:');
        exibirQRCode(result.base64);
    } else if (result.instance?.state === 'open') {
        log.success('Instância já está conectada!');
    } else {
        log.warning('QR Code não disponível. Tente novamente.');
    }

    return result;
}

function exibirQRCode(base64Data) {
    console.log(`\n${colors.cyan}${'='.repeat(50)}`);
    console.log('  ESCANEIE O QR CODE COM SEU WHATSAPP');
    console.log(`${'='.repeat(50)}${colors.reset}\n`);

    log.info(`Acesse: ${EVOLUTION_URL}/instance/connect/<instancia>`);

    // Salva como arquivo
    const fs = require('fs');
    const path = `/tmp/qrcode_${Date.now()}.png`;

    try {
        let data = base64Data;
        if (data.includes(',')) {
            data = data.split(',')[1];
        }
        fs.writeFileSync(path, Buffer.from(data, 'base64'));
        log.info(`QR Code salvo em: ${path}`);
    } catch (e) {
        log.warning('Não foi possível salvar QR Code como arquivo');
    }
}

async function verificarStatus(nome) {
    log.info(`Verificando status: ${nome}`);

    const result = await apiRequest(`/instance/connectionState/${nome}`);

    if (result.error) {
        log.error(`Erro: ${JSON.stringify(result.message)}`);
        return;
    }

    const state = result.instance?.state || 'unknown';

    switch (state) {
        case 'open':
            log.success(`Instância '${nome}' está CONECTADA`);
            break;
        case 'close':
            log.warning(`Instância '${nome}' está DESCONECTADA`);
            break;
        case 'connecting':
            log.info(`Instância '${nome}' está CONECTANDO...`);
            break;
        default:
            log.info(`Status da instância '${nome}': ${state}`);
    }

    return result;
}

async function listarInstancias() {
    log.info('Listando todas as instâncias...');

    const result = await apiRequest('/instance/fetchInstances');

    if (result.error) {
        log.error(`Erro: ${JSON.stringify(result.message)}`);
        return;
    }

    if (!result || result.length === 0) {
        log.warning('Nenhuma instância encontrada');
        return [];
    }

    console.log(`\n${colors.bold}${'Nome'.padEnd(25)} ${'Status'.padEnd(15)} ${'Número'.padEnd(15)}${colors.reset}`);
    console.log('-'.repeat(55));

    for (const inst of result) {
        const nome = inst.instance?.instanceName || 'N/A';
        const status = inst.instance?.state || 'N/A';
        const numero = inst.instance?.owner || 'N/A';

        let statusColor = colors.yellow;
        if (status === 'open') statusColor = colors.green;
        else if (status === 'close') statusColor = colors.red;

        console.log(`${nome.padEnd(25)} ${statusColor}${status.padEnd(15)}${colors.reset} ${numero.padEnd(15)}`);
    }

    console.log();
    return result;
}

async function deletarInstancia(nome) {
    log.warning(`Deletando instância: ${nome}`);

    const result = await apiRequest(`/instance/delete/${nome}`, 'DELETE');

    if (result.error) {
        log.error(`Erro: ${JSON.stringify(result.message)}`);
        return;
    }

    log.success(`Instância '${nome}' deletada com sucesso!`);
    return result;
}

async function logoutInstancia(nome) {
    log.info(`Desconectando instância: ${nome}`);

    const result = await apiRequest(`/instance/logout/${nome}`, 'DELETE');

    if (result.error) {
        log.error(`Erro: ${JSON.stringify(result.message)}`);
        return;
    }

    log.success(`Logout da instância '${nome}' realizado!`);
    return result;
}

async function enviarMensagem(nome, numero, texto) {
    log.info(`Enviando mensagem para ${numero}...`);

    const data = { number: numero, text: texto };
    const result = await apiRequest(`/message/sendText/${nome}`, 'POST', data);

    if (result.error) {
        log.error(`Erro: ${JSON.stringify(result.message)}`);
        return;
    }

    log.success('Mensagem enviada com sucesso!');
    return result;
}

function mostrarAjuda() {
    console.log(`
${colors.bold}${colors.cyan}╔══════════════════════════════════════════════════════════╗
║         EVOLUTION API MANAGER - Hub Automação Pro        ║
╚══════════════════════════════════════════════════════════╝${colors.reset}

${colors.bold}Uso:${colors.reset}
    node evolution_manager.js <comando> [argumentos]

${colors.bold}Comandos disponíveis:${colors.reset}

    ${colors.green}criar${colors.reset} <nome>          Cria nova instância e gera QR Code
    ${colors.green}qrcode${colors.reset} <nome>         Obtém QR Code para conectar
    ${colors.green}status${colors.reset} <nome>         Verifica status da conexão
    ${colors.green}listar${colors.reset}                Lista todas as instâncias
    ${colors.green}deletar${colors.reset} <nome>        Remove uma instância
    ${colors.green}logout${colors.reset} <nome>         Desconecta o WhatsApp
    ${colors.green}enviar${colors.reset} <nome> <num> <msg>  Envia mensagem de texto

${colors.bold}Exemplos:${colors.reset}
    node evolution_manager.js criar cliente-empresa-abc
    node evolution_manager.js qrcode cliente-empresa-abc
    node evolution_manager.js enviar cliente-empresa-abc 5511999999999 "Olá!"
`);
}

async function main() {
    const args = process.argv.slice(2);

    if (args.length === 0) {
        mostrarAjuda();
        process.exit(0);
    }

    const comando = args[0].toLowerCase();

    switch (comando) {
        case 'help':
        case '-h':
        case '--help':
            mostrarAjuda();
            break;

        case 'criar':
            if (!args[1]) {
                log.error('Uso: node evolution_manager.js criar <nome-instancia>');
                process.exit(1);
            }
            await criarInstancia(args[1]);
            break;

        case 'qrcode':
            if (!args[1]) {
                log.error('Uso: node evolution_manager.js qrcode <nome-instancia>');
                process.exit(1);
            }
            await obterQRCode(args[1]);
            break;

        case 'status':
            if (!args[1]) {
                log.error('Uso: node evolution_manager.js status <nome-instancia>');
                process.exit(1);
            }
            await verificarStatus(args[1]);
            break;

        case 'listar':
            await listarInstancias();
            break;

        case 'deletar':
            if (!args[1]) {
                log.error('Uso: node evolution_manager.js deletar <nome-instancia>');
                process.exit(1);
            }
            await deletarInstancia(args[1]);
            break;

        case 'logout':
            if (!args[1]) {
                log.error('Uso: node evolution_manager.js logout <nome-instancia>');
                process.exit(1);
            }
            await logoutInstancia(args[1]);
            break;

        case 'enviar':
            if (args.length < 4) {
                log.error('Uso: node evolution_manager.js enviar <nome> <numero> <mensagem>');
                process.exit(1);
            }
            await enviarMensagem(args[1], args[2], args.slice(3).join(' '));
            break;

        default:
            log.error(`Comando desconhecido: ${comando}`);
            mostrarAjuda();
            process.exit(1);
    }
}

main();
