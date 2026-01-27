#!/usr/bin/env python3
"""
Evolution API Manager - Gerenciador de Instâncias WhatsApp
Hub Automação Pro

Uso:
    python evolution_manager.py criar <nome-instancia>
    python evolution_manager.py qrcode <nome-instancia>
    python evolution_manager.py status <nome-instancia>
    python evolution_manager.py listar
    python evolution_manager.py deletar <nome-instancia>
    python evolution_manager.py logout <nome-instancia>
"""

import os
import sys
import json
import base64
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError
from dotenv import load_dotenv

# Carrega variáveis do .env
load_dotenv()

# Configurações
EVOLUTION_URL = os.getenv('EVOLUTION_SERVER_URL', 'http://localhost:8080')
API_KEY = os.getenv('EVOLUTION_API_KEY', 'sua-chave-global-evolution-aqui')

# Cores para terminal
class Colors:
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    RED = '\033[91m'
    BLUE = '\033[94m'
    CYAN = '\033[96m'
    RESET = '\033[0m'
    BOLD = '\033[1m'

def print_success(msg):
    print(f"{Colors.GREEN}✓ {msg}{Colors.RESET}")

def print_error(msg):
    print(f"{Colors.RED}✗ {msg}{Colors.RESET}")

def print_info(msg):
    print(f"{Colors.BLUE}ℹ {msg}{Colors.RESET}")

def print_warning(msg):
    print(f"{Colors.YELLOW}⚠ {msg}{Colors.RESET}")

def api_request(endpoint, method='GET', data=None):
    """Faz requisição à Evolution API"""
    url = f"{EVOLUTION_URL}{endpoint}"
    headers = {
        'apikey': API_KEY,
        'Content-Type': 'application/json'
    }

    try:
        body = json.dumps(data).encode('utf-8') if data else None
        req = Request(url, data=body, headers=headers, method=method)

        with urlopen(req, timeout=30) as response:
            return json.loads(response.read().decode('utf-8'))
    except HTTPError as e:
        error_body = e.read().decode('utf-8')
        try:
            return {'error': True, 'status': e.code, 'message': json.loads(error_body)}
        except:
            return {'error': True, 'status': e.code, 'message': error_body}
    except URLError as e:
        return {'error': True, 'message': f'Erro de conexão: {e.reason}'}
    except Exception as e:
        return {'error': True, 'message': str(e)}

def criar_instancia(nome):
    """Cria uma nova instância WhatsApp"""
    print_info(f"Criando instância: {nome}")

    data = {
        "instanceName": nome,
        "qrcode": True,
        "integration": "WHATSAPP-BAILEYS"
    }

    result = api_request('/instance/create', 'POST', data)

    if result.get('error'):
        print_error(f"Erro ao criar: {result.get('message')}")
        return None

    print_success(f"Instância '{nome}' criada com sucesso!")

    # Se retornou QR Code, exibe
    if 'qrcode' in result:
        print_info("QR Code gerado! Escaneie com seu WhatsApp:")
        exibir_qrcode(result['qrcode'].get('base64', ''))

    return result

def obter_qrcode(nome):
    """Obtém QR Code de uma instância"""
    print_info(f"Obtendo QR Code da instância: {nome}")

    result = api_request(f'/instance/connect/{nome}')

    if result.get('error'):
        print_error(f"Erro: {result.get('message')}")
        return None

    if 'base64' in result:
        print_success("QR Code obtido! Escaneie com seu WhatsApp:")
        exibir_qrcode(result['base64'])
    elif result.get('instance', {}).get('state') == 'open':
        print_success("Instância já está conectada!")
    else:
        print_warning("QR Code não disponível. Tente novamente.")

    return result

def exibir_qrcode(base64_data):
    """Exibe QR Code no terminal usando caracteres ASCII"""
    if not base64_data:
        print_warning("QR Code vazio")
        return

    # Remove prefixo data:image se existir
    if ',' in base64_data:
        base64_data = base64_data.split(',')[1]

    print(f"\n{Colors.CYAN}{'='*50}")
    print("  ESCANEIE O QR CODE COM SEU WHATSAPP")
    print(f"{'='*50}{Colors.RESET}\n")

    # Tenta usar qrcode lib se disponível, senão mostra base64
    try:
        import qrcode
        # Se tem a lib, gera QR no terminal
        print_info("Instale 'qrcode' para ver no terminal: pip install qrcode")
    except ImportError:
        pass

    # Salva como imagem para visualização alternativa
    try:
        img_path = f"/tmp/qrcode_{os.path.basename(base64_data[:20])}.png"
        with open(img_path, 'wb') as f:
            f.write(base64.b64decode(base64_data))
        print_info(f"QR Code salvo em: {img_path}")
        print_info("Abra o arquivo para escanear ou use o endpoint da Evolution:")
        print(f"   {Colors.CYAN}{EVOLUTION_URL}/instance/connect/<instancia>{Colors.RESET}\n")
    except Exception as e:
        print_warning(f"Não foi possível salvar imagem: {e}")
        print_info(f"Acesse: {EVOLUTION_URL}/instance/connect/<instancia>")

def verificar_status(nome):
    """Verifica status de uma instância"""
    print_info(f"Verificando status: {nome}")

    result = api_request(f'/instance/connectionState/{nome}')

    if result.get('error'):
        print_error(f"Erro: {result.get('message')}")
        return None

    state = result.get('instance', {}).get('state', 'unknown')

    if state == 'open':
        print_success(f"Instância '{nome}' está CONECTADA")
    elif state == 'close':
        print_warning(f"Instância '{nome}' está DESCONECTADA")
    elif state == 'connecting':
        print_info(f"Instância '{nome}' está CONECTANDO...")
    else:
        print_info(f"Status da instância '{nome}': {state}")

    return result

def listar_instancias():
    """Lista todas as instâncias"""
    print_info("Listando todas as instâncias...")

    result = api_request('/instance/fetchInstances')

    if result.get('error'):
        print_error(f"Erro: {result.get('message')}")
        return None

    if not result:
        print_warning("Nenhuma instância encontrada")
        return []

    print(f"\n{Colors.BOLD}{'Nome':<25} {'Status':<15} {'Número':<15}{Colors.RESET}")
    print("-" * 55)

    for inst in result:
        nome = inst.get('instance', {}).get('instanceName', 'N/A')
        status = inst.get('instance', {}).get('state', 'N/A')
        numero = inst.get('instance', {}).get('owner', 'N/A')

        # Cor baseada no status
        if status == 'open':
            status_color = Colors.GREEN
        elif status == 'close':
            status_color = Colors.RED
        else:
            status_color = Colors.YELLOW

        print(f"{nome:<25} {status_color}{status:<15}{Colors.RESET} {numero:<15}")

    print()
    return result

def deletar_instancia(nome):
    """Deleta uma instância"""
    print_warning(f"Deletando instância: {nome}")

    result = api_request(f'/instance/delete/{nome}', 'DELETE')

    if result.get('error'):
        print_error(f"Erro: {result.get('message')}")
        return None

    print_success(f"Instância '{nome}' deletada com sucesso!")
    return result

def logout_instancia(nome):
    """Faz logout de uma instância"""
    print_info(f"Desconectando instância: {nome}")

    result = api_request(f'/instance/logout/{nome}', 'DELETE')

    if result.get('error'):
        print_error(f"Erro: {result.get('message')}")
        return None

    print_success(f"Logout da instância '{nome}' realizado!")
    return result

def enviar_mensagem(nome, numero, texto):
    """Envia mensagem de texto"""
    print_info(f"Enviando mensagem para {numero}...")

    data = {
        "number": numero,
        "text": texto
    }

    result = api_request(f'/message/sendText/{nome}', 'POST', data)

    if result.get('error'):
        print_error(f"Erro: {result.get('message')}")
        return None

    print_success("Mensagem enviada com sucesso!")
    return result

def mostrar_ajuda():
    """Mostra ajuda do CLI"""
    print(f"""
{Colors.BOLD}{Colors.CYAN}╔══════════════════════════════════════════════════════════╗
║         EVOLUTION API MANAGER - Hub Automação Pro        ║
╚══════════════════════════════════════════════════════════╝{Colors.RESET}

{Colors.BOLD}Uso:{Colors.RESET}
    python evolution_manager.py <comando> [argumentos]

{Colors.BOLD}Comandos disponíveis:{Colors.RESET}

    {Colors.GREEN}criar{Colors.RESET} <nome>          Cria nova instância e gera QR Code
    {Colors.GREEN}qrcode{Colors.RESET} <nome>         Obtém QR Code para conectar
    {Colors.GREEN}status{Colors.RESET} <nome>         Verifica status da conexão
    {Colors.GREEN}listar{Colors.RESET}                Lista todas as instâncias
    {Colors.GREEN}deletar{Colors.RESET} <nome>        Remove uma instância
    {Colors.GREEN}logout{Colors.RESET} <nome>         Desconecta o WhatsApp
    {Colors.GREEN}enviar{Colors.RESET} <nome> <num> <msg>  Envia mensagem de texto

{Colors.BOLD}Exemplos:{Colors.RESET}
    python evolution_manager.py criar cliente-empresa-abc
    python evolution_manager.py qrcode cliente-empresa-abc
    python evolution_manager.py status cliente-empresa-abc
    python evolution_manager.py listar
    python evolution_manager.py enviar cliente-empresa-abc 5511999999999 "Olá!"

{Colors.BOLD}Configuração:{Colors.RESET}
    Defina as variáveis no arquivo .env:
    - EVOLUTION_SERVER_URL=http://localhost:8080
    - EVOLUTION_API_KEY=sua-chave-aqui
""")

def main():
    if len(sys.argv) < 2:
        mostrar_ajuda()
        sys.exit(0)

    comando = sys.argv[1].lower()

    if comando in ['help', '-h', '--help']:
        mostrar_ajuda()

    elif comando == 'criar':
        if len(sys.argv) < 3:
            print_error("Uso: python evolution_manager.py criar <nome-instancia>")
            sys.exit(1)
        criar_instancia(sys.argv[2])

    elif comando == 'qrcode':
        if len(sys.argv) < 3:
            print_error("Uso: python evolution_manager.py qrcode <nome-instancia>")
            sys.exit(1)
        obter_qrcode(sys.argv[2])

    elif comando == 'status':
        if len(sys.argv) < 3:
            print_error("Uso: python evolution_manager.py status <nome-instancia>")
            sys.exit(1)
        verificar_status(sys.argv[2])

    elif comando == 'listar':
        listar_instancias()

    elif comando == 'deletar':
        if len(sys.argv) < 3:
            print_error("Uso: python evolution_manager.py deletar <nome-instancia>")
            sys.exit(1)
        deletar_instancia(sys.argv[2])

    elif comando == 'logout':
        if len(sys.argv) < 3:
            print_error("Uso: python evolution_manager.py logout <nome-instancia>")
            sys.exit(1)
        logout_instancia(sys.argv[2])

    elif comando == 'enviar':
        if len(sys.argv) < 5:
            print_error("Uso: python evolution_manager.py enviar <nome> <numero> <mensagem>")
            sys.exit(1)
        enviar_mensagem(sys.argv[2], sys.argv[3], ' '.join(sys.argv[4:]))

    else:
        print_error(f"Comando desconhecido: {comando}")
        mostrar_ajuda()
        sys.exit(1)

if __name__ == '__main__':
    main()
