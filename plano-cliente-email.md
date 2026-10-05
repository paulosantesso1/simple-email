# Plano: Cliente de E-mail Leve e Acessível

## 1. Objetivo

Criar um programa de e-mail para Windows que seja leve, rápido e totalmente acessível com o NVDA. A inspiração são as primeiras versões do Thunderbird: poucas funções, todas funcionando bem.

A regra mais importante do projeto: **acessibilidade vem antes de aparência**. Se uma escolha deixa o programa mais bonito mas pior de usar com leitor de tela, ela fica de fora.

## 2. Tecnologia

- **Linguagem:** Python.
- **Interface:** wxPython. Ele usa os botões, listas e caixas de texto padrão do próprio Windows, que o NVDA já sabe ler sem esforço extra. O próprio NVDA é feito com wxPython.
- **Conexão com o servidor:** IMAP para receber e organizar, SMTP para enviar. As duas já vêm prontas no Python (bibliotecas `imaplib` e `smtplib`).
- **Cópia local dos e-mails:** um arquivo SQLite. Funciona como um caderno onde o programa anota os e-mails já baixados, para abrir rápido sem buscar tudo de novo no servidor.
- **Senhas:** guardadas no Gerenciador de Credenciais do Windows, usando a biblioteca `keyring`. Nunca em arquivo de texto.

### Por que IMAP

IMAP é como um armário no correio: os e-mails ficam lá, e o programa só abre e olha. Tudo que você faz aqui (apagar, mover, marcar como lido) acontece também no servidor. Assim, o celular e o computador mostram sempre a mesma coisa.

## 3. Funções

### 3.1 Contas
- Adicionar, editar e remover contas.
- Mais de uma conta ao mesmo tempo.
- Preenchimento automático dos servidores para provedores comuns (Gmail, Outlook, Yahoo, UOL, Terra). Para os outros, o usuário digita.

### 3.2 Pastas
- Mostrar todas as pastas que existem no servidor: Caixa de Entrada, Enviados, Spam, Lixeira, Rascunhos e as criadas pelo usuário.
- Criar, renomear e apagar pastas.
- Mover e-mails entre pastas.

### 3.3 Ler e-mails
- Lista de mensagens com remetente, assunto, data e se foi lida.
- Abrir a mensagem e ler o texto.
- E-mails em HTML: mostrar a versão em texto simples. Opção de abrir a versão completa no navegador padrão.
- Anexos: ver a lista e salvar no computador.

### 3.4 Escrever e responder
- Novo e-mail.
- Responder.
- Responder a todos.
- Encaminhar (com os anexos originais).
- Anexar arquivos.
- Salvar como rascunho.

### 3.5 Catálogo de endereços
Fica no menu Ferramentas.
- Adicionar, editar e apagar contatos (nome e e-mail).
- Ao digitar no campo "Para", sugerir contatos já salvos.
- Opção de salvar o remetente de um e-mail como contato.

### 3.6 Sincronização
- Ao abrir o programa, buscar novidades.
- Botão e atalho para verificar e-mails manualmente.
- Verificação automática a cada X minutos (configurável).

## 4. Regras de acessibilidade

1. Usar só controles padrão do wxPython. Nada de desenhar elementos personalizados.
2. Todo campo, botão e lista com nome claro, que o NVDA anuncie corretamente.
3. Tudo acessível pelo teclado, sem exceção.
4. Ordem do Tab lógica: pastas, depois lista de mensagens, depois leitura.
5. Atalhos parecidos com os do Thunderbird e Outlook, para quem já está acostumado:
   - Ctrl+N: novo e-mail
   - Ctrl+R: responder
   - Ctrl+Shift+R: responder a todos
   - Ctrl+L: encaminhar
   - Delete: apagar
   - F5: verificar e-mails
   - Ctrl+Enter: enviar
6. Avisos importantes (e-mail enviado, erro de conexão) anunciados pelo leitor de tela, sem roubar o foco.
7. Testar cada etapa com NVDA antes de seguir para a próxima.

## 5. Fora do escopo (por enquanto)

Para manter o programa leve, não entram na primeira versão:
- Calendário e tarefas.
- Filtros e regras automáticas.
- Criptografia de mensagens (PGP).
- Aparência e temas.
- Versão para celular.

## 6. Riscos conhecidos

- **Login no Gmail e Outlook:** esses provedores, em geral, não aceitam mais a senha normal em programas de terceiros. O Gmail pede uma "senha de app" (exige verificação em duas etapas ligada). A Microsoft passou a exigir um tipo de login moderno chamado OAuth, que é como um crachá temporário dado pelo próprio site da Microsoft. Isso dá mais trabalho e deve ser confirmado na hora de construir a etapa de contas.
- **Pastas com nomes diferentes:** cada provedor chama as pastas de um jeito ("Sent", "Enviados", "[Gmail]/Enviados"). O programa precisa identificar qual é qual.

## 7. Etapas de construção

Cada etapa termina com um teste no NVDA.

1. **Base:** janela principal com três áreas (pastas, lista, leitura) e menus. Sem e-mail ainda, só a estrutura navegável.
2. **Uma conta, só leitura:** conectar por IMAP, listar pastas e mensagens, ler o texto.
3. **Envio:** novo e-mail, responder, responder a todos, encaminhar, anexos.
4. **Organização:** apagar, mover, marcar como lido, criar e renomear pastas.
5. **Cópia local:** guardar no SQLite para abrir mais rápido.
6. **Várias contas.**
7. **Catálogo de endereços.**
8. **Verificação automática e ajustes finais.**

## 8. Como trabalhar com o Claude Code

- Pedir uma etapa por vez, colando a seção correspondente deste plano.
- Ao fim de cada etapa, testar com NVDA e relatar o que o leitor anunciou ou deixou de anunciar.
- Manter este arquivo atualizado quando alguma decisão mudar.

## 9. Estado do projeto e decisões tomadas

Todas as etapas da seção 7 foram construídas. Como rodar: `Simple Email.bat` (usa o ambiente virtual `.venv`). Dependências em `requirements.txt` (wxPython e keyring).

Decisões que mudaram ou detalharam o plano:

- **Leitura da lista:** cada mensagem é uma linha de texto: `Não lida, Remetente; Assunto: ...; Data: ...`. O "Não lida," some depois de lida.
- **Leitura da mensagem:** abre em janela própria (Enter abre, Esc fecha e volta para a lista), como página web (WebView2 do Windows) para o NVDA navegar por títulos (H) e links (K). Scripts e imagens remotas ficam bloqueados; o botão "Abrir no navegador" mostra a versão completa.
- **Anexos:** lista própria na janela da mensagem, com botões para baixar o selecionado ou todos.
- **Gmail:** exige senha de app; o diálogo de conta explica e traz o link. Outlook/Hotmail com OAuth continua sem suporte.
- **Avisos:** confirmações (e-mail enviado, rascunho salvo etc.) aparecem em uma janelinha que se fecha sozinha, porque é o que o NVDA lê de forma confiável.
- **Seleção múltipla:** apagar, mover e marcar funcionam em várias mensagens, com barra de progresso. Shift+Delete apaga de vez, com confirmação que pode ser desligada.
- **Contas:** árvore "Contas e pastas", com as contas recolhidas; abrir uma conta mostra as pastas. O programa lembra a última conta e pasta abertas.
- **Cópia local:** SQLite em `%APPDATA%\SimpleEmail\cache.db` (pode ser apagado sem perder nada). Contatos ficam em `contatos.json`, opções em `opcoes.json`.
- **Verificação automática:** a cada 5 minutos por padrão (configurável em Ferramentas, Opções; 0 desliga), com som e aviso rápido quando chega e-mail novo.
- **Atalhos:** lista completa em Ajuda, Atalhos de teclado (F1).
