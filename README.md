# Simple Email

Um cliente de e-mail para Windows, leve, rápido e **feito para ser usado com leitor de tela (NVDA)**. A inspiração são as primeiras versões do Thunderbird: poucas funções, todas funcionando bem.

A regra mais importante do projeto: **acessibilidade vem antes de aparência**. Se uma escolha deixa o programa mais bonito mas pior de usar com leitor de tela, ela fica de fora.

## Funções

- **Várias contas** (IMAP/SMTP), mostradas numa árvore "Contas e pastas". As contas começam recolhidas; abrir uma mostra as pastas. O programa lembra a última conta e pasta abertas.
- **Pastas:** criar, renomear, apagar e mover mensagens entre elas. Os nomes das pastas especiais (Enviados, Lixeira, Spam, Rascunhos) são reconhecidos em qualquer provedor.
- **Ler e-mails:** a mensagem abre numa janela própria (Enter abre, Esc fecha e volta para a lista), como página web, para o NVDA navegar por títulos (H), links (K) e as outras teclas de navegação. Scripts e imagens remotas ficam bloqueados.
- **Anexos:** lista própria na janela da mensagem, com botões para baixar o selecionado ou todos.
- **Escrever:** novo, responder, responder a todos, encaminhar (com os anexos originais), anexar arquivos e salvar rascunho. Rascunhos podem ser reabertos para editar. Em Para, Cc e Cco, cada endereço digitado (Enter) entra numa lista, e Delete remove um por um; os anexos também aceitam seleção múltipla e Delete.
- **Seleção múltipla:** apagar, mover e marcar como lida/não lida em várias mensagens de uma vez, com barra de progresso. Shift+Delete apaga de vez. Arquivo > Esvaziar lixeira apaga tudo da lixeira, sempre com confirmação.
- **Catálogo de endereços:** contatos com sugestões ao digitar em Para, Cc e Cco, e opção de salvar o remetente de uma mensagem.
- **Cópia local (SQLite):** a janela abre na hora e só busca o que mudou; mensagens já lidas abrem mesmo sem internet.
- **Verificação automática** a cada X minutos (configurável), com som e aviso quando chega e-mail novo. Os avisos (e-mail enviado, rascunho salvo etc.) usam notificações do Windows, lidas pelo NVDA sem pausar a navegação.

## Requisitos

- Windows 10 ou 11 (usa o componente WebView2 do Windows para exibir as mensagens)
- Python 3.10 ou mais novo
- [NVDA](https://www.nvaccess.org/) recomendado

## Como instalar e rodar

Use sempre um ambiente virtual:

```bash
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
.venv\Scripts\python email_app.py
```

Depois da instalação, o arquivo `Simple Email.bat` abre o programa sem janela de terminal.

## Primeiro uso e contas

Na primeira vez, o programa pede os dados da conta. Os servidores de Gmail, Outlook/Hotmail, Yahoo, UOL, BOL e Terra são preenchidos sozinhos.

- **Gmail:** não aceita a senha normal. É preciso uma **senha de app** (exige a verificação em duas etapas ligada). O diálogo de conta explica o passo a passo e traz o link: <https://myaccount.google.com/apppasswords>.
- **Outlook/Hotmail:** a Microsoft passou a exigir login moderno (OAuth), que ainda não é suportado.
- As senhas ficam no **Gerenciador de Credenciais do Windows** (biblioteca `keyring`), nunca em arquivo de texto.

## Atalhos principais

| Atalho | Ação |
| --- | --- |
| F1 | Lista completa de atalhos |
| F5 | Verificar e-mails |
| Ctrl+N | Nova mensagem |
| Ctrl+R / Ctrl+Shift+R | Responder / responder a todos |
| Ctrl+L | Encaminhar |
| Ctrl+Enter | Enviar (ao escrever) |
| Ctrl+S | Salvar rascunho (ao escrever) |
| Ctrl+K | Catálogo de endereços (ao escrever) |
| Delete / Shift+Delete | Mover para a Lixeira / apagar de vez |
| Ctrl+Shift+M | Mover para outra pasta |
| Ctrl+Q / Ctrl+U | Marcar como lida / não lida |
| Ctrl+PgDn / Ctrl+PgUp | Próxima conta / conta anterior |
| Enter / Esc | Abrir mensagem / fechar e voltar para a lista |

## Onde ficam os dados

Tudo em `%APPDATA%\SimpleEmail`:

- `config.json` — contas (sem senhas)
- `opcoes.json` — opções do programa
- `contatos.json` — catálogo de endereços
- `cache.db` — cópia local dos e-mails (pode ser apagada sem perder nada; tudo é baixado de novo do servidor)
- `erro.log` — erros inesperados, se houver

## Estrutura do código

| Arquivo | O que faz |
| --- | --- |
| `email_app.py` | Janela principal, árvore de contas e pastas, leitura e fluxos |
| `imap_client.py` | Conexão IMAP: pastas, sincronização, organização |
| `mailer.py` | Montagem e envio (SMTP), respostas e encaminhamentos |
| `cache.py` | Cópia local em SQLite |
| `config.py` | Contas, senhas (keyring) e opções |
| `render.py` | Página HTML segura exibida na leitura |
| `compose_dialog.py` | Janela de escrever |
| `contatos.py`, `contatos_dialog.py` | Catálogo de endereços |
| `opcoes_dialog.py` | Opções e lista de atalhos |

O plano original do projeto, com as decisões tomadas, está em [`plano-cliente-email.md`](plano-cliente-email.md).

## Limitações conhecidas

- Sem OAuth (Outlook/Hotmail) por enquanto.
- A cópia local guarda as 100 mensagens mais recentes de cada pasta.
- No Gmail, pastas são marcadores: apagar pela pasta "Todos os e-mails" age de forma diferente do esperado.
- Fora do escopo desta versão: calendário e tarefas, filtros e regras, criptografia PGP, temas e versão para celular.

## Licença

Distribuído sob a licença [Apache 2.0](LICENSE).
