"""Cliente de e-mail leve e acessível: janela principal e diálogos."""
import os
import re
import sys
import tempfile
import threading
import traceback
from email.utils import getaddresses
from pathlib import Path

import wx
import wx.adv
import wx.html2

import config
import mailer
import oauth
import opcoes_dialog
from avisos import APP_NAME, avisar
from cache import Cache
from compose_dialog import ID_RASCUNHO, ComposeDialog
from contatos_dialog import ContatosDialog, salvar_remetente
from imap_client import ImapClient, encontrar_links
from opcoes_dialog import AtalhosDialog, OpcoesDialog
from render import montar_pagina

# Cada tarefa em segundo plano guarda a conta que estava ativa quando foi pedida,
# para que trocar de conta no meio não leve a operação para o servidor errado.
_ctx = threading.local()


def texto_da_linha(m):
    """Texto lido pelo NVDA: 'Não lida, ' só aparece enquanto a mensagem não foi lida."""
    base = f"{m['remetente']}; Assunto: {m['assunto']}; Data: {m['data']}"
    return base if m["lida"] else f"Não lida, {base}"


class AccountDialog(wx.Dialog):
    def __init__(self, parent, conta=None):
        super().__init__(parent, title="Conta de e-mail")
        self.conta = conta
        self.host_automatico = True
        # Login pelo navegador (OAuth): e-mail para o qual há autorização e, se acabou
        # de ser feita, o token de renovação a guardar.
        self.email_oauth = conta["email"] if conta and conta.get("auth") == "oauth" else None
        self.refresh = None

        aviso = wx.StaticText(
            self,
            label="Para Outlook, Hotmail e Live, digite o e-mail e use o botão Entrar pelo navegador, "
            "sem precisar de senha. Para os outros provedores, use a senha. No Gmail, não use a senha "
            "normal, e sim uma senha de app: ative a verificação em duas etapas na sua conta Google, "
            "abra o link abaixo, dê um nome, por exemplo Simple Email, clique em Criar e cole no campo "
            "Senha a senha de 16 letras.",
        )
        aviso.Wrap(460)
        link = wx.adv.HyperlinkCtrl(
            self, label="Gerar senha de app do Gmail",
            url="https://myaccount.google.com/apppasswords", name="Gerar senha de app do Gmail",
        )
        self.botao_oauth = wx.Button(self, label="Entrar pelo na&vegador (Outlook e Hotmail)")
        self.botao_oauth.Bind(wx.EVT_BUTTON, self.on_oauth)

        # Cada rótulo é criado logo antes do seu campo: é assim que o NVDA
        # associa o nome ao campo.
        grade = wx.FlexGridSizer(2, 8, 8)
        grade.AddGrowableCol(1, 1)
        campos = []
        for rotulo, estilo, valor in (
            ("S&eu nome:", 0, ""),
            ("&E-mail:", 0, ""),
            ("&Senha:", wx.TE_PASSWORD, ""),
            ("Servidor &IMAP (receber):", 0, ""),
            ("&Porta IMAP:", 0, "993"),
            ("Servidor S&MTP (enviar):", 0, ""),
            ("P&orta SMTP:", 0, "465"),
        ):
            r = wx.StaticText(self, label=rotulo)
            campo = wx.TextCtrl(self, value=valor, style=estilo, name=rotulo.replace("&", "").rstrip(":"))
            grade.Add(r, 0, wx.ALIGN_CENTER_VERTICAL)
            grade.Add(campo, 1, wx.EXPAND)
            campos.append(campo)
        self.nome, self.email, self.senha, self.host, self.porta, self.smtp, self.smtp_porta = campos

        raiz = wx.BoxSizer(wx.VERTICAL)
        raiz.Add(aviso, 0, wx.ALL, 12)
        raiz.Add(link, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 12)
        raiz.Add(grade, 0, wx.EXPAND | wx.LEFT | wx.RIGHT, 12)
        raiz.Add(self.botao_oauth, 0, wx.ALL, 12)
        raiz.Add(self.CreateStdDialogButtonSizer(wx.OK | wx.CANCEL), 0, wx.ALL | wx.ALIGN_RIGHT, 12)
        self.SetSizerAndFit(raiz)

        if conta:
            self.nome.SetValue(conta.get("nome", ""))
            self.email.SetValue(conta["email"])
            self.host.SetValue(conta["host"])
            self.porta.SetValue(str(conta["porta"]))
            self.smtp.SetValue(conta.get("smtp_host", ""))
            self.smtp_porta.SetValue(str(conta.get("smtp_porta", 465)))
            self.host_automatico = False
            self.senha.SetHint("Deixe em branco para manter o login atual")

        self.email.Bind(wx.EVT_KILL_FOCUS, self.on_email_perdeu_foco)
        self.host.Bind(wx.EVT_TEXT, lambda e: setattr(self, "host_automatico", False)
                       if self.FindFocus() is self.host else None)
        self.Bind(wx.EVT_BUTTON, self.on_ok, id=wx.ID_OK)
        self.email.SetFocus()

    def on_email_perdeu_foco(self, evento):
        evento.Skip()
        sugestao = config.servidor_sugerido(self.email.GetValue())
        if sugestao and self.host_automatico:
            self.host.SetValue(sugestao[0])
            self.porta.SetValue(str(sugestao[1]))
            self.smtp.SetValue(sugestao[2])
            self.smtp_porta.SetValue(str(sugestao[3]))

    def on_ok(self, evento):
        email, host = self.email.GetValue().strip(), self.host.GetValue().strip()
        senha = self.senha.GetValue()
        if not email or "@" not in email:
            return self._erro("Digite um endereço de e-mail válido.", self.email)
        if not host:
            return self._erro("Digite o servidor IMAP.", self.host)
        if not self.porta.GetValue().strip().isdigit():
            return self._erro("A porta IMAP deve ser um número.", self.porta)
        if not self.smtp.GetValue().strip():
            return self._erro("Digite o servidor SMTP.", self.smtp)
        if not self.smtp_porta.GetValue().strip().isdigit():
            return self._erro("A porta SMTP deve ser um número.", self.smtp_porta)
        if self._usa_oauth():
            if email != self.email_oauth:
                return self._erro("O e-mail mudou depois do login pelo navegador. "
                                  "Use o botão Entrar pelo navegador de novo.", self.botao_oauth)
        elif not senha and not (self.conta and self.conta.get("auth") != "oauth" and self.conta["email"] == email):
            return self._erro("Digite a senha ou use o botão Entrar pelo navegador.", self.senha)
        evento.Skip()

    def _usa_oauth(self):
        """Digitar uma senha troca o login pelo navegador por senha comum."""
        return bool(self.email_oauth) and not self.senha.GetValue()

    def on_oauth(self, evento):
        email = self.email.GetValue().strip()
        if not email or "@" not in email:
            return self._erro("Digite primeiro o seu endereço de e-mail.", self.email)
        if not oauth.suporta(email):
            return self._erro("O login pelo navegador está disponível para Outlook, Hotmail e Live. "
                              "Para os outros provedores, use a senha.", self.email)
        cancelar, saida = threading.Event(), {}

        espera = wx.Dialog(self, title="Entrar pelo navegador")
        texto = wx.StaticText(
            espera, label="O navegador foi aberto na página de login da Microsoft. Entre na conta "
            f"{email}, aceite o acesso e volte aqui. Esta janela fecha sozinha ao terminar. "
            "Para desistir, use Cancelar.")
        texto.Wrap(420)
        caixa = wx.BoxSizer(wx.VERTICAL)
        caixa.Add(texto, 0, wx.ALL, 12)
        caixa.Add(espera.CreateStdDialogButtonSizer(wx.CANCEL), 0, wx.ALL | wx.ALIGN_RIGHT, 12)
        espera.SetSizerAndFit(caixa)

        def trabalho():
            try:
                saida["refresh"] = oauth.autorizar(email, cancelar)
            except Exception as e:  # noqa: BLE001
                saida["erro"] = e
            if not cancelar.is_set():
                wx.CallAfter(espera.EndModal, wx.ID_OK)

        threading.Thread(target=trabalho, daemon=True).start()
        if espera.ShowModal() != wx.ID_OK:
            cancelar.set()
        espera.Destroy()
        if cancelar.is_set():
            return
        if "erro" in saida:
            return self._erro(str(saida["erro"]), self.botao_oauth)
        self.email_oauth, self.refresh = email, saida["refresh"]
        self.senha.SetValue("")
        wx.MessageBox("Login na Microsoft concluído. Clique em OK para salvar a conta.",
                      "Conta de e-mail", wx.OK | wx.ICON_INFORMATION, self)
        self.FindWindowById(wx.ID_OK, self).SetFocus()

    def _erro(self, texto, campo):
        wx.MessageBox(texto, "Conta de e-mail", wx.OK | wx.ICON_WARNING, self)
        campo.SetFocus()

    def resultado(self):
        conta = {
            "nome": self.nome.GetValue().strip(),
            "smtp_host": self.smtp.GetValue().strip(),
            "smtp_porta": int(self.smtp_porta.GetValue()),
            "email": self.email.GetValue().strip(),
            "host": self.host.GetValue().strip(),
            "porta": int(self.porta.GetValue()),
        }
        if self._usa_oauth():
            conta["auth"] = "oauth"
        else:
            self.refresh = None
        return conta, self.senha.GetValue()


class LinksDialog(wx.Dialog):
    """Lista os links da mensagem; Enter abre o escolhido no navegador. Esc fecha."""

    def __init__(self, parent, links):
        super().__init__(parent, title="Links da mensagem")
        rotulo = wx.StaticText(self, label="&Links")
        self.lista = wx.ListBox(self, choices=links, name="Links")
        self.lista.SetSelection(0)
        botoes = self.CreateStdDialogButtonSizer(wx.OK | wx.CANCEL)
        self.FindWindowById(wx.ID_OK, self).SetLabel("&Abrir no navegador")
        self.FindWindowById(wx.ID_CANCEL, self).SetLabel("&Fechar")
        raiz = wx.BoxSizer(wx.VERTICAL)
        raiz.Add(rotulo, 0, wx.ALL, 8)
        raiz.Add(self.lista, 1, wx.EXPAND | wx.LEFT | wx.RIGHT, 8)
        raiz.Add(botoes, 0, wx.ALL | wx.ALIGN_RIGHT, 8)
        self.SetSizerAndFit(raiz)
        self.SetMinSize((520, 300))
        self.SetSize((620, 350))
        self.Bind(wx.EVT_BUTTON, self.on_abrir, id=wx.ID_OK)
        self.lista.Bind(wx.EVT_LISTBOX_DCLICK, self.on_abrir)
        self.lista.SetFocus()

    def on_abrir(self, evento):
        i = self.lista.GetSelection()
        if i != wx.NOT_FOUND:
            wx.LaunchDefaultBrowser(self.lista.GetString(i))
        self.EndModal(wx.ID_OK)


class MessageDialog(wx.Dialog):
    """Leitura de uma mensagem em texto simples. Esc fecha e devolve o foco para a lista."""

    def __init__(self, parent, dados):
        super().__init__(parent, title=dados["assunto"], size=(800, 550),
                         style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
        self.dados = dados
        cabecalho = f"De: {dados['de']}\nPara: {dados['para']}\nAssunto: {dados['assunto']}\nData: {dados['data']}\n"
        if dados["anexos"]:
            cabecalho += "Anexos: " + "; ".join(dados["anexos"]) + "\n"
        completo = f"{cabecalho}\n{dados['texto']}"
        self.links = encontrar_links(completo)

        rotulo = wx.StaticText(self, label="&Mensagem")
        self.texto = wx.TextCtrl(
            self, value=completo,
            style=wx.TE_MULTILINE | wx.TE_READONLY | wx.TE_RICH2 | wx.TE_AUTO_URL,
            name="Mensagem",
        )
        botao_links = wx.Button(self, wx.ID_ANY, f"&Links ({len(self.links)})")
        botao_links.Enable(bool(self.links))
        botao_html = wx.Button(self, wx.ID_ANY, "Abrir no &navegador")
        botao_html.Enable(bool(dados.get("html")))
        fechar = wx.Button(self, wx.ID_CANCEL, "&Fechar")

        botoes = wx.BoxSizer(wx.HORIZONTAL)
        botoes.Add(botao_links, 0, wx.RIGHT, 8)
        b_contato = wx.Button(self, wx.ID_ANY, "&Salvar remetente como contato")
        b_contato.Bind(wx.EVT_BUTTON, lambda e: salvar_remetente(self, dados["de"]))
        botoes.Add(b_contato, 0, wx.RIGHT, 8)
        botoes.Add(botao_html, 0, wx.RIGHT, 8)
        botoes.Add(fechar)
        raiz = wx.BoxSizer(wx.VERTICAL)
        raiz.Add(rotulo, 0, wx.ALL, 8)
        raiz.Add(self.texto, 1, wx.EXPAND | wx.LEFT | wx.RIGHT, 8)
        raiz.Add(botoes, 0, wx.ALL | wx.ALIGN_RIGHT, 8)
        self.SetSizer(raiz)
        self.SetEscapeId(wx.ID_CANCEL)

        botao_links.Bind(wx.EVT_BUTTON, self.on_links)
        botao_html.Bind(wx.EVT_BUTTON, self.on_html)
        self.texto.Bind(wx.EVT_TEXT_URL, self.on_clique_url)
        self.texto.SetInsertionPoint(0)
        self.texto.SetFocus()

    def on_clique_url(self, evento):
        if evento.GetMouseEvent().LeftUp():
            wx.LaunchDefaultBrowser(self.texto.GetRange(evento.GetURLStart(), evento.GetURLEnd()))
        evento.Skip()

    def on_links(self, evento):
        dlg = LinksDialog(self, self.links)
        dlg.ShowModal()
        dlg.Destroy()

    def on_html(self, evento):
        """Abre a versão completa (HTML) da mensagem no navegador padrão."""
        arquivo = Path(tempfile.gettempdir()) / "SimpleEmail-mensagem.html"
        arquivo.write_text(
            '<meta charset="utf-8">' + self.dados["html"], encoding="utf-8"
        )
        wx.LaunchDefaultBrowser(arquivo.as_uri())


class WebMessageDialog(wx.Dialog):
    """Leitura da mensagem como página: o NVDA entra no modo de navegação
    (H para títulos, K para links etc.). Esc fecha e volta para a lista."""

    def __init__(self, parent, dados):
        super().__init__(parent, title=dados["assunto"], size=(900, 650),
                         style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
        self.dados = dados
        self.web = wx.html2.WebView.New(self, backend=wx.html2.WebViewBackendEdge,
                                        name="Mensagem")
        self.web.EnableContextMenu(False)
        self.web.EnableAccessToDevTools(False)
        self.web.AddScriptMessageHandler("wx")
        self.web.AddUserScript(
            'document.addEventListener("keydown",function(e){'
            'if(e.key==="Escape"){window.wx.postMessage("esc");}'
            'else if(e.ctrlKey&&(e.key==="r"||e.key==="R")){e.preventDefault();'
            'window.wx.postMessage(e.shiftKey?"todos":"responder");}'
            'else if(e.ctrlKey&&(e.key==="l"||e.key==="L")){e.preventDefault();'
            'window.wx.postMessage("encaminhar");}});'
        )
        self.acao = None
        self.anexos = mailer.anexos_originais(dados["raw"]) if dados.get("anexos") else []
        # Ordem do Tab: página, lista de anexos, baixar selecionado, baixar todos, botões.
        rot_anexos = wx.StaticText(self, label="A&nexos")
        self.lista_anexos = wx.ListBox(self, name="Anexos",
                                       choices=[a["nome"] for a in self.anexos])
        self.b_sel = wx.Button(self, wx.ID_ANY, "&Baixar anexo selecionado")
        self.b_todos = wx.Button(self, wx.ID_ANY, "Baixar &todos os anexos")
        if self.anexos:
            self.lista_anexos.SetSelection(0)
        else:
            for w in (rot_anexos, self.lista_anexos, self.b_sel, self.b_todos):
                w.Hide()
        self.b_sel.Bind(wx.EVT_BUTTON, self.baixar_selecionado)
        self.b_todos.Bind(wx.EVT_BUTTON, self.baixar_todos)
        botao_html = wx.Button(self, wx.ID_ANY, "Abrir no &navegador")
        botao_html.Enable(bool(dados.get("html")))
        fechar = wx.Button(self, wx.ID_CANCEL, "&Fechar")

        botoes = wx.BoxSizer(wx.HORIZONTAL)
        for acao, rotulo in (("responder", "&Responder (Ctrl+R)"),
                             ("todos", "Responder a &todos (Ctrl+Shift+R)"),
                             ("encaminhar", "&Encaminhar (Ctrl+L)")):
            b = wx.Button(self, wx.ID_ANY, rotulo)
            b.Bind(wx.EVT_BUTTON, lambda e, a=acao: self.escolher(a))
            botoes.Add(b, 0, wx.RIGHT, 8)
        botoes.Add(botao_html, 0, wx.RIGHT, 8)
        botoes.Add(fechar)
        raiz = wx.BoxSizer(wx.VERTICAL)
        raiz.Add(self.web, 1, wx.EXPAND | wx.ALL, 8)
        raiz.Add(rot_anexos, 0, wx.LEFT | wx.RIGHT, 8)
        linha_anexos = wx.BoxSizer(wx.HORIZONTAL)
        linha_anexos.Add(self.lista_anexos, 1, wx.EXPAND | wx.RIGHT, 8)
        col_b = wx.BoxSizer(wx.VERTICAL)
        col_b.Add(self.b_sel, 0, wx.BOTTOM, 6)
        col_b.Add(self.b_todos)
        linha_anexos.Add(col_b)
        raiz.Add(linha_anexos, 0, wx.EXPAND | wx.ALL, 8)
        raiz.Add(botoes, 0, wx.ALL | wx.ALIGN_RIGHT, 8)
        self.SetSizer(raiz)
        self.SetEscapeId(wx.ID_CANCEL)

        botao_html.Bind(wx.EVT_BUTTON, self.on_html)
        self.Bind(wx.html2.EVT_WEBVIEW_SCRIPT_MESSAGE_RECEIVED, self.on_script)
        self.Bind(wx.html2.EVT_WEBVIEW_NAVIGATING, self.on_navegar)
        self.Bind(wx.html2.EVT_WEBVIEW_NEWWINDOW, self.on_nova_janela)
        self.Bind(wx.html2.EVT_WEBVIEW_LOADED, lambda e: self.web.SetFocus())
        self.Bind(wx.EVT_CHAR_HOOK, self.on_tecla)

        pagina = montar_pagina(dados)
        if len(pagina) > 1_500_000:  # limite do componente para páginas carregadas direto
            pagina = montar_pagina({**dados, "html": None})
        self.web.SetPage(pagina, "about:blank")

    # ---------- anexos ----------
    def _nomes_unicos(self):
        vistos, nomes = {}, []
        for a in self.anexos:
            base = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", os.path.basename(a["nome"])) or "anexo"
            n = vistos.get(base.lower(), 0)
            vistos[base.lower()] = n + 1
            raiz, ext = os.path.splitext(base)
            nomes.append(base if n == 0 else f"{raiz} ({n + 1}){ext}")
        return nomes

    def baixar_selecionado(self, evento):
        i = self.lista_anexos.GetSelection()
        if i == wx.NOT_FOUND:
            return
        nome = self._nomes_unicos()[i]
        dlg = wx.FileDialog(self, "Salvar anexo", defaultFile=nome,
                            style=wx.FD_SAVE | wx.FD_OVERWRITE_PROMPT)
        if dlg.ShowModal() == wx.ID_OK:
            try:
                with open(dlg.GetPath(), "wb") as f:
                    f.write(self.anexos[i]["dados"])
                avisar(f"Anexo {nome} salvo.", self)
            except OSError as e:
                wx.MessageBox(f"Não foi possível salvar:\n{e}", APP_NAME, wx.OK | wx.ICON_ERROR, self)
        dlg.Destroy()
        self.lista_anexos.SetFocus()

    def baixar_todos(self, evento):
        dlg = wx.DirDialog(self, "Escolha a pasta para salvar os anexos")
        if dlg.ShowModal() == wx.ID_OK:
            try:
                for a, nome in zip(self.anexos, self._nomes_unicos()):
                    with open(os.path.join(dlg.GetPath(), nome), "wb") as f:
                        f.write(a["dados"])
                n = len(self.anexos)
                avisar(f"{n} anexo salvo." if n == 1 else f"{n} anexos salvos.", self)
            except OSError as e:
                wx.MessageBox(f"Não foi possível salvar:\n{e}", APP_NAME, wx.OK | wx.ICON_ERROR, self)
        dlg.Destroy()
        self.b_todos.SetFocus()

    def escolher(self, acao):
        self.acao = acao
        self.EndModal(wx.ID_OK)

    def on_script(self, evento):
        msg = evento.GetString()
        if msg == "esc":
            self.EndModal(wx.ID_CANCEL)
        elif msg in ("responder", "todos", "encaminhar"):
            self.escolher(msg)

    def on_tecla(self, evento):
        k = evento.GetKeyCode()
        if k == wx.WXK_ESCAPE:
            self.EndModal(wx.ID_CANCEL)
        elif evento.ControlDown() and k in (ord("R"), ord("r")):
            self.escolher("todos" if evento.ShiftDown() else "responder")
        elif evento.ControlDown() and k in (ord("L"), ord("l")):
            self.escolher("encaminhar")
        else:
            evento.Skip()

    def on_navegar(self, evento):
        """Só a própria página pode carregar aqui. Links http(s) e mailto abrem fora do programa;
        qualquer outro destino (file:, javascript: ...) é barrado."""
        url = evento.GetURL()
        evento.Veto() if not url.lower().startswith(("about:", "data:")) else evento.Skip()
        if url.lower().startswith(("http://", "https://", "mailto:")):
            wx.LaunchDefaultBrowser(url)

    def on_nova_janela(self, evento):
        url = evento.GetURL()
        if url.lower().startswith(("http://", "https://", "mailto:")):
            wx.LaunchDefaultBrowser(url)

    def on_html(self, evento):
        """Abre a versão completa (HTML original) no navegador padrão."""
        arquivo = Path(tempfile.gettempdir()) / "SimpleEmail-mensagem.html"
        arquivo.write_text('<meta charset="utf-8">' + self.dados["html"], encoding="utf-8")
        wx.LaunchDefaultBrowser(arquivo.as_uri())


def web_disponivel():
    try:
        return wx.html2.WebView.IsBackendAvailable(wx.html2.WebViewBackendEdge)
    except Exception:  # noqa: BLE001
        return False


class ContasDialog(wx.Dialog):
    """Lista de contas: adicionar, editar e remover."""

    def __init__(self, principal):
        super().__init__(principal, title="Contas de e-mail")
        self.principal = principal
        rotulo = wx.StaticText(self, label="C&ontas")
        self.lista = wx.ListBox(self, name="Contas", size=(380, 160))
        b_add = wx.Button(self, wx.ID_ANY, "&Adicionar...")
        b_edit = wx.Button(self, wx.ID_ANY, "&Editar...")
        b_rem = wx.Button(self, wx.ID_ANY, "&Remover")
        fechar = wx.Button(self, wx.ID_CANCEL, "&Fechar")
        col = wx.BoxSizer(wx.VERTICAL)
        for b in (b_add, b_edit, b_rem, fechar):
            col.Add(b, 0, wx.EXPAND | wx.BOTTOM, 6)
        linha = wx.BoxSizer(wx.HORIZONTAL)
        linha.Add(self.lista, 1, wx.EXPAND | wx.RIGHT, 8)
        linha.Add(col)
        raiz = wx.BoxSizer(wx.VERTICAL)
        raiz.Add(rotulo, 0, wx.ALL, 8)
        raiz.Add(linha, 1, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)
        self.SetSizerAndFit(raiz)
        self.SetEscapeId(wx.ID_CANCEL)
        b_add.Bind(wx.EVT_BUTTON, lambda e: (principal.adicionar_conta(self),
                                             self.atualizar(len(principal.contas) - 1)))
        b_edit.Bind(wx.EVT_BUTTON, self.on_editar)
        b_rem.Bind(wx.EVT_BUTTON, self.on_remover)
        self.atualizar(0)
        self.lista.SetFocus()

    def atualizar(self, selecionar=0):
        self.lista.Set([c["email"] for c in self.principal.contas])
        if self.principal.contas:
            self.lista.SetSelection(max(0, min(selecionar, len(self.principal.contas) - 1)))

    def on_editar(self, evento):
        i = self.lista.GetSelection()
        if i != wx.NOT_FOUND:
            self.principal.editar_conta(i, self)
            self.atualizar(i)
        self.lista.SetFocus()

    def on_remover(self, evento):
        i = self.lista.GetSelection()
        if i != wx.NOT_FOUND:
            self.principal.remover_conta(i, self)
            self.atualizar(0)
        self.lista.SetFocus()


class MainFrame(wx.Frame):
    def __init__(self):
        super().__init__(None, title=APP_NAME, size=(1000, 650))
        self.cache = Cache()
        self.clientes = {}
        self.trava_clientes = threading.Lock()
        self.pastas_por_conta = {}
        self.pasta_exibida = None
        self.contas = config.carregar_contas()
        ultima = config.opcao("ultima_conta", None)  # a conta aberta por último
        self.conta_atual = self._conta_por_email(ultima) or (self.contas[0] if self.contas else None)
        self.nos_contas = {}
        self._prog = 0  # >0 enquanto o programa mexe na árvore (ignora eventos de seleção)
        self.mensagens = []
        self.token = 0
        self.timer_pasta = None
        self._verificando = False
        self._pendentes = set()  # (conta, pasta, uid) apagados/movidos e ainda não confirmados
        self.timer_auto = wx.Timer(self)
        self.Bind(wx.EVT_TIMER, lambda e: self.verificar_automatico(), self.timer_auto)
        self.Bind(wx.EVT_CLOSE, self.on_fechar)

        self._criar_menus()
        self._criar_controles()
        self.CreateStatusBar()
        self.Centre()
        self._montar_arvore()
        self.arvore.SetFocus()

        if self.conta_atual:
            self.conectar()
        else:
            self.SetStatusText("Nenhuma conta configurada.")
            wx.CallAfter(self.adicionar_conta)
        self._reiniciar_timer()
        wx.CallLater(6000, self.verificar_automatico)  # ao abrir, busca novidades nas outras contas

    # ---------- conta ativa ----------
    @property
    def conta(self):
        return getattr(_ctx, "conta", None) or self.conta_atual

    @property
    def imap(self):
        return self._cliente(self.conta)

    @property
    def pastas_info(self):
        c = self.conta
        return self.pastas_por_conta.get(c["email"], []) if c else []

    @pastas_info.setter
    def pastas_info(self, valor):
        self.pastas_por_conta[self.conta["email"]] = valor

    def _cliente(self, conta):
        """Conexão IMAP da conta (uma por conta, criada na primeira vez que é usada)."""
        with self.trava_clientes:
            c = self.clientes.get(conta["email"])
            if c is None:
                c = ImapClient()
                token = (lambda conta=conta: oauth.token_de_acesso(conta)) if conta.get("auth") == "oauth" else None
                c.configurar(conta["host"], conta["porta"], conta["email"],
                             "" if token else config.obter_senha(conta["email"]), token)
                self.clientes[conta["email"]] = c
            return c

    def _conta_por_email(self, email):
        return next((c for c in self.contas if c["email"] == email), None)

    # ---------- menus ----------
    def _criar_menus(self):
        barra = wx.MenuBar()

        m_arquivo = wx.Menu()
        self._item(m_arquivo, "&Nova mensagem\tCtrl+N", lambda e: self.compor({}))
        self._item(m_arquivo, "&Verificar e-mails\tF5", self.on_verificar)
        self._item(m_arquivo, "Pró&xima conta\tCtrl+PgDn", lambda e: self._mover_conta(1))
        self._item(m_arquivo, "Conta a&nterior\tCtrl+PgUp", lambda e: self._mover_conta(-1))
        self._item(m_arquivo, "Esvaziar &lixeira...", lambda e: self.esvaziar_lixeira())
        m_arquivo.AppendSeparator()
        self._item(m_arquivo, "&Sair\tAlt+F4", lambda e: self.Close())
        barra.Append(m_arquivo, "&Arquivo")

        m_msg = wx.Menu()
        self._item(m_msg, "&Responder\tCtrl+R", lambda e: self.responder("responder"))
        self._item(m_msg, "Responder a &todos\tCtrl+Shift+R", lambda e: self.responder("todos"))
        self._item(m_msg, "&Encaminhar\tCtrl+L", lambda e: self.responder("encaminhar"))
        m_msg.AppendSeparator()
        self._item(m_msg, "&Apagar\tDelete", self.on_apagar)
        self._item(m_msg, "Apagar de &vez\tShift+Delete", self.on_apagar_de_vez)
        self._item(m_msg, "&Mover para...\tCtrl+Shift+M", lambda e: self.mover_mensagem())
        self._item(m_msg, "&Salvar remetente como contato\tCtrl+Shift+A",
                   lambda e: self.salvar_remetente_selecionado())
        self._item(m_msg, "Marcar como &lida\tCtrl+Q", lambda e: self.marcar(True))
        self._item(m_msg, "Marcar como &não lida\tCtrl+U", lambda e: self.marcar(False))
        barra.Append(m_msg, "&Mensagem")

        m_pasta = wx.Menu()
        self._item(m_pasta, "&Nova pasta...", lambda e: self.nova_pasta())
        self._item(m_pasta, "&Renomear pasta...\tF2", lambda e: self.renomear_pasta())
        self._item(m_pasta, "&Apagar pasta...", lambda e: self.apagar_pasta())
        barra.Append(m_pasta, "&Pasta")

        m_ferr = wx.Menu()
        self._item(m_ferr, "&Contas...", lambda e: self.gerenciar_contas())
        self._item(m_ferr, "Catálogo de &endereços...", lambda e: self.abrir_catalogo())
        self._item(m_ferr, "&Opções...", lambda e: self.abrir_opcoes())
        barra.Append(m_ferr, "&Ferramentas")

        m_ajuda = wx.Menu()
        self._item(m_ajuda, "Atalhos de &teclado\tF1", lambda e: self.mostrar_atalhos())
        self._item(m_ajuda, "&Sobre", self.on_sobre)
        barra.Append(m_ajuda, "A&juda")
        self.SetMenuBar(barra)

    def _item(self, menu, texto, handler):
        item = menu.Append(wx.ID_ANY, texto)
        self.Bind(wx.EVT_MENU, handler, item)

    # ---------- controles ----------
    def _criar_controles(self):
        painel = wx.Panel(self)
        rot_pastas = wx.StaticText(painel, label="&Contas e pastas")
        self.arvore = wx.TreeCtrl(
            painel, name="Contas e pastas",
            style=wx.TR_HAS_BUTTONS | wx.TR_LINES_AT_ROOT | wx.TR_HIDE_ROOT | wx.TR_SINGLE)
        self.raiz = self.arvore.AddRoot("Contas")

        rot_lista = wx.StaticText(painel, label="&Mensagens")
        self.lista = wx.ListCtrl(
            painel, style=wx.LC_REPORT | wx.LC_NO_HEADER, name="Mensagens"
        )
        self.lista.InsertColumn(0, "Mensagem", width=600)

        col_esq = wx.BoxSizer(wx.VERTICAL)
        col_esq.Add(rot_pastas, 0, wx.BOTTOM, 4)
        col_esq.Add(self.arvore, 1, wx.EXPAND)
        col_dir = wx.BoxSizer(wx.VERTICAL)
        col_dir.Add(rot_lista, 0, wx.BOTTOM, 4)
        col_dir.Add(self.lista, 1, wx.EXPAND)
        raiz = wx.BoxSizer(wx.HORIZONTAL)
        raiz.Add(col_esq, 1, wx.EXPAND | wx.ALL, 8)
        raiz.Add(col_dir, 3, wx.EXPAND | wx.TOP | wx.RIGHT | wx.BOTTOM, 8)
        painel.SetSizer(raiz)

        self.arvore.Bind(wx.EVT_TREE_SEL_CHANGED, self.on_arvore_selecao)
        self.arvore.Bind(wx.EVT_TREE_ITEM_EXPANDING, self.on_arvore_expandindo)
        self.arvore.Bind(wx.EVT_TREE_ITEM_ACTIVATED, self.on_arvore_ativada)
        self.lista.Bind(wx.EVT_LIST_ITEM_ACTIVATED, self.on_abrir)
        self.lista.Bind(wx.EVT_SIZE, self.on_lista_tamanho)

    def on_lista_tamanho(self, evento):
        evento.Skip()
        self.lista.SetColumnWidth(0, max(200, self.lista.GetClientSize().GetWidth() - 4))

    # ---------- trabalho em segundo plano ----------
    def _em_thread(self, trabalho, ao_terminar):
        self._em_thread_com_erro(trabalho, ao_terminar, self._erro)

    def _em_thread_com_erro(self, trabalho, ao_terminar, ao_falhar):
        conta = self.conta

        def corpo():
            _ctx.conta = conta
            try:
                resultado = trabalho()
            except Exception as e:  # noqa: BLE001 - mostramos qualquer falha ao usuário
                wx.CallAfter(ao_falhar, e)
                return
            wx.CallAfter(ao_terminar, resultado)
        threading.Thread(target=corpo, daemon=True).start()

    def _erro(self, e):
        self.SetStatusText("Erro.")
        texto = str(e)
        if "application-specific password" in texto.lower():
            texto += (
                "\n\nO Gmail exige uma senha de app. Em Ferramentas, Contas, "
                "há o link para gerá-la."
            )
        wx.MessageBox(f"Ocorreu um erro:\n{texto}", APP_NAME, wx.OK | wx.ICON_ERROR, self)

    # ---------- contas e pastas (árvore) ----------
    def _montar_arvore(self):
        """Uma linha por conta, recolhida. Só a conta ativa tem as pastas guardadas por baixo."""
        self._prog += 1
        self.arvore.DeleteChildren(self.raiz)
        self.nos_contas = {}
        for c in self.contas:
            item = self.arvore.AppendItem(self.raiz, c["email"])
            self.arvore.SetItemData(item, ("conta", c["email"]))
            self.arvore.SetItemHasChildren(item, True)
            self.nos_contas[c["email"]] = item
        self._prog -= 1
        if self.conta_atual:
            self._montar_pastas()
            self._selecionar_no(self.nos_contas[self.conta_atual["email"]])

    def _montar_pastas(self):
        email = self.conta["email"]
        nodo = self.nos_contas.get(email)
        if nodo is None:
            return
        self._prog += 1
        self.arvore.DeleteChildren(nodo)
        for i, p in enumerate(self.pastas_info):
            filho = self.arvore.AppendItem(nodo, p["nome"])
            self.arvore.SetItemData(filho, ("pasta", email, i))
        self.arvore.SetItemHasChildren(nodo, True)
        self._prog -= 1

    def _selecionar_no(self, item):
        self._prog += 1
        self.arvore.SelectItem(item)
        self._prog -= 1

    def _dado(self, item):
        return self.arvore.GetItemData(item) if item and item.IsOk() else None

    def _pasta_selecionada(self):
        """Índice da pasta marcada na árvore (na conta ativa), ou wx.NOT_FOUND."""
        dado = self._dado(self.arvore.GetSelection())
        if dado and dado[0] == "pasta" and self.conta_atual and dado[1] == self.conta_atual["email"]:
            return dado[2]
        return wx.NOT_FOUND

    def _indice_exibido(self):
        """Índice da pasta que está aparecendo na lista de mensagens."""
        return next((i for i, p in enumerate(self.pastas_info)
                     if p["raw"] == self.pasta_exibida), wx.NOT_FOUND)

    def on_arvore_selecao(self, evento):
        if self._prog:
            return
        dado = self._dado(evento.GetItem())
        if dado and dado[0] == "pasta" and self.conta_atual and dado[1] == self.conta_atual["email"]:
            # Espera um instante: quem anda rápido pelas pastas não dispara uma busca por pasta.
            if self.timer_pasta:
                self.timer_pasta.Stop()
            self.timer_pasta = wx.CallLater(300, self._carregar_pasta_se_existe, dado[2])

    def _carregar_pasta_se_existe(self, i):
        if 0 <= i < len(self.pastas_info):
            self._carregar_pasta(i)

    def on_arvore_expandindo(self, evento):
        dado = self._dado(evento.GetItem())
        if dado and dado[0] == "conta":
            conta = self._conta_por_email(dado[1])
            if conta is not self.conta_atual:
                self._ativar(conta)
            wx.CallAfter(self._recolher_outras)
        evento.Skip()

    def _recolher_outras(self):
        self._prog += 1
        for email, item in self.nos_contas.items():
            if self.conta_atual and email != self.conta_atual["email"] and self.arvore.IsExpanded(item):
                self.arvore.Collapse(item)
        self._prog -= 1

    def on_arvore_ativada(self, evento):
        """Enter: numa conta, abre ou fecha a lista de pastas; numa pasta, vai para as mensagens."""
        item = evento.GetItem()
        dado = self._dado(item)
        if dado and dado[0] == "conta":
            if self.arvore.IsExpanded(item):
                self.arvore.Collapse(item)
            else:
                self.arvore.Expand(item)
        elif dado and dado[0] == "pasta":
            self.lista.SetFocus()

    def _mover_conta(self, passo):
        if len(self.contas) < 2 or not self.conta_atual:
            return
        i = (self.contas.index(self.conta_atual) + passo) % len(self.contas)
        self._ativar(self.contas[i])
        self._selecionar_no(self.nos_contas[self.conta_atual["email"]])
        avisar(f"Conta {self.conta_atual['email']}", self)

    def _ativar(self, conta):
        """Passa a mostrar outra conta: esvazia a conta anterior e abre a nova."""
        anterior = self.conta_atual
        self.conta_atual = conta
        no_anterior = self.nos_contas.get(anterior["email"]) if anterior else None
        if no_anterior is not None and anterior is not conta:
            self._prog += 1
            self.arvore.Collapse(no_anterior)
            self.arvore.DeleteChildren(no_anterior)
            self.arvore.SetItemHasChildren(no_anterior, True)
            self._prog -= 1
        self._reiniciar()

    def _reiniciar(self):
        self.token += 1
        self.pasta_exibida = None
        self.mensagens = []
        self.lista.DeleteAllItems()
        if self.conta_atual:
            self.conectar()
        else:
            self.SetStatusText("Nenhuma conta configurada.")

    def _aplicar_contas(self, ativa_email, reiniciar):
        """Depois de adicionar, editar ou remover: relê as contas e refaz a árvore."""
        self.contas = config.carregar_contas()
        self.conta_atual = self._conta_por_email(ativa_email) if ativa_email else None
        self._montar_arvore()
        if reiniciar:
            self._reiniciar()

    def gerenciar_contas(self):
        dlg = ContasDialog(self)
        dlg.ShowModal()
        dlg.Destroy()
        self.arvore.SetFocus()
        if not self.contas:
            self.adicionar_conta()

    def adicionar_conta(self, pai=None):
        dlg = AccountDialog(pai or self, None)
        if dlg.ShowModal() == wx.ID_OK:
            conta, senha = dlg.resultado()
            if self._conta_por_email(conta["email"]):
                wx.MessageBox("Essa conta já está cadastrada.", APP_NAME,
                              wx.OK | wx.ICON_INFORMATION, dlg)
            else:
                try:
                    config.salvar_conta(conta, senha, refresh=dlg.refresh)
                except Exception as e:  # noqa: BLE001
                    dlg.Destroy()
                    return self._erro(e)
                self._aplicar_contas(conta["email"], reiniciar=True)  # a nova fica embaixo das outras
        dlg.Destroy()

    def editar_conta(self, i, pai=None):
        antiga = self.contas[i]
        dlg = AccountDialog(pai or self, antiga)
        if dlg.ShowModal() == wx.ID_OK:
            conta, senha = dlg.resultado()
            try:
                config.salvar_conta(conta, senha or None, antigo=antiga["email"], refresh=dlg.refresh)
            except Exception as e:  # noqa: BLE001
                dlg.Destroy()
                return self._erro(e)
            for email in {antiga["email"], conta["email"]}:
                self.clientes.pop(email, None)  # a conexão antiga usava os dados velhos
                if email != conta["email"]:
                    self.cache.remover_conta(email)
                    self.pastas_por_conta.pop(email, None)
            era_a_atual = antiga is self.conta_atual
            self._aplicar_contas(conta["email"] if era_a_atual else self.conta_atual["email"],
                                 reiniciar=era_a_atual)
        dlg.Destroy()

    def remover_conta(self, i, pai=None):
        conta = self.contas[i]
        r = wx.MessageBox(
            f"Remover a conta {conta['email']} deste programa? Os e-mails continuam no servidor.",
            APP_NAME, wx.YES_NO | wx.NO_DEFAULT | wx.ICON_WARNING, pai or self)
        if r != wx.YES:
            return
        config.remover_conta(conta["email"])
        self.cache.remover_conta(conta["email"])
        self.clientes.pop(conta["email"], None)
        self.pastas_por_conta.pop(conta["email"], None)
        era_a_atual = conta is self.conta_atual
        restantes = [c for c in self.contas if c is not conta]
        if era_a_atual:
            self._aplicar_contas(restantes[0]["email"] if restantes else None, reiniciar=True)
        else:
            self._aplicar_contas(self.conta_atual["email"], reiniciar=False)

    def conectar(self):
        email = self.conta["email"]
        em_cache = self.cache.pastas(email)
        if em_cache and not self.pastas_info:
            self._pastas_prontas(em_cache)  # a janela já abre com o que temos guardado
        self.SetStatusText(f"Conectando a {email}...")

        def listar():
            pastas = self.imap.listar_pastas()
            self.cache.salvar_pastas(email, pastas)
            return pastas

        self._em_thread_com_erro(
            listar, lambda pastas: self._pastas_do_servidor(email, pastas),
            lambda e: self._falha_conexao(email, e))

    def _falha_conexao(self, email, e):
        _registrar(f"Falha ao conectar em {email}: {type(e).__name__}: {e}")
        if not self.conta_atual or email != self.conta_atual["email"]:
            return
        if self.pastas_info:
            self.SetStatusText("Sem conexão. Mostrando a cópia local.")
        else:
            self._erro(e)

    def _pastas_do_servidor(self, email, pastas):
        if not self.conta_atual or email != self.conta_atual["email"]:
            self.pastas_por_conta[email] = pastas  # a conta já não é a que está na tela
            return
        if [p["raw"] for p in pastas] == [p["raw"] for p in self.pastas_info]:
            self.pastas_info = pastas
            return
        self._pastas_prontas(pastas, self.pasta_exibida)

    def _pastas_prontas(self, pastas, selecionar=None):
        """Mostra as pastas da conta ativa (recolhidas até o usuário abrir) e carrega uma."""
        self.pastas_info = pastas
        self._montar_pastas()
        if not pastas:
            return
        email = self.conta["email"]
        if selecionar is None:
            selecionar = config.opcao("pasta:" + email, None)  # a pasta aberta por último
        i = next((n for n, p in enumerate(pastas) if p["raw"] == selecionar), 0)
        nodo = self.nos_contas.get(email)
        if nodo is not None and self.arvore.IsExpanded(nodo) and selecionar == self.pasta_exibida:
            filhos = self._filhos(nodo)
            if i < len(filhos) and self.arvore.HasFocus():
                self._selecionar_no(filhos[i])  # a seleção estava nessa pasta: mantém
        self._carregar_pasta(i)

    def _filhos(self, nodo):
        filhos, (filho, cookie) = [], self.arvore.GetFirstChild(nodo)
        while filho.IsOk():
            filhos.append(filho)
            filho, cookie = self.arvore.GetNextChild(nodo, cookie)
        return filhos

    def _recarregar_pastas(self, selecionar=None):
        conta = self.conta["email"]

        def listar():
            pastas = self.imap.listar_pastas()
            self.cache.salvar_pastas(conta, pastas)
            return pastas

        self._em_thread(
            listar,
            lambda pastas: (self._pastas_prontas(pastas, selecionar)
                            if self.conta_atual and conta == self.conta_atual["email"] else None))

    def _carregar_pasta(self, indice):
        self.token += 1
        token = self.token
        pasta = self.pastas_info[indice]
        conta = self.conta["email"]
        config.salvar_opcao("ultima_conta", conta)
        config.salvar_opcao("pasta:" + conta, pasta["raw"])
        mostrou_cache = bool(self.cache.validade(conta, pasta["raw"]))
        if mostrou_cache:
            self._mostrar_mensagens(pasta, self.cache.mensagens(conta, pasta["raw"]))
            self.SetStatusText(f"{pasta['nome']}: atualizando...")
        else:
            self.SetStatusText(f"Carregando {pasta['nome']}...")

        def sincronizar():
            return self._sincronizar_pasta(pasta["raw"])

        def falhou(e):
            if mostrou_cache:
                self.SetStatusText(f"{pasta['nome']}: sem conexão, mostrando a cópia local.")
            else:
                self._erro(e)

        self._em_thread_com_erro(
            sincronizar,
            lambda res: token == self.token and self._sincronizada(pasta, res),
            falhou)

    def _sincronizada(self, pasta, res):
        msgs, novas = res
        self._mostrar_mensagens(pasta, msgs, True)
        entrada = self._pasta_raw("Caixa de Entrada") or "INBOX"
        if novas and pasta["raw"] == entrada:
            self._avisar_novas([(self.conta["email"], novas)])

    def _sincronizar_pasta(self, raw):
        """(Em segundo plano) Atualiza a cópia local da pasta da conta ativa.
        Devolve (mensagens, quantas novas não lidas chegaram)."""
        conta = self.conta["email"]
        antiga = self.cache.validade(conta, raw)
        r = self.imap.sincronizar(raw, self.cache.uids(conta, raw))
        if antiga and r["validade"] != antiga:  # o servidor renumerou a pasta
            self.cache.limpar_pasta(conta, raw)
            antiga = None
            r = self.imap.sincronizar(raw, set())
        pend = {u for (e, p, u) in list(self._pendentes) if e == conta and p == raw}
        if pend:
            r["novos"] = [m for m in r["novos"] if m["uid"] not in pend]
            r["uids"] = [u for u in r["uids"] if u not in pend]
        self.cache.aplicar_sincronizacao(conta, raw, r)
        # Na primeira sincronização tudo é "novo"; só avisa do que chegou depois.
        novas = sum(1 for m in r["novos"] if not m["lida"]) if antiga else 0
        return self.cache.mensagens(conta, raw), novas

    # ---------- verificação automática ----------
    def _reiniciar_timer(self):
        self.timer_auto.Stop()
        minutos = opcoes_dialog.opcao("intervalo_verificacao")
        if minutos and minutos > 0:
            self.timer_auto.Start(int(minutos * 60 * 1000))

    def verificar_automatico(self):
        """Olha a Caixa de Entrada de todas as contas (e a pasta aberta) e avisa de e-mail novo."""
        if self._verificando or not self.contas:
            return
        self._verificando = True
        contas = list(self.contas)
        atual = self.conta_atual
        exibida = self.pasta_exibida

        def trabalho():
            resultados = []
            for conta in contas:
                _ctx.conta = conta
                email = conta["email"]
                raw = self._pasta_raw("Caixa de Entrada", email) or "INBOX"
                alvos = [raw]
                if conta is atual and exibida and exibida != raw:
                    alvos.append(exibida)
                for alvo in alvos:
                    try:
                        _, novas = self._sincronizar_pasta(alvo)
                    except Exception:  # noqa: BLE001 - sem conexão: tenta de novo na próxima vez
                        continue
                    resultados.append((email, alvo, novas if alvo == raw else 0))
            return resultados

        self._em_thread_com_erro(
            trabalho, self._verificacao_pronta,
            lambda e: (setattr(self, "_verificando", False),
                       self.SetStatusText("Não consegui verificar e-mails agora.")))

    def _verificacao_pronta(self, resultados):
        self._verificando = False
        # Atualiza a lista se a pasta que está na tela foi sincronizada.
        if self.conta_atual and self.pasta_exibida:
            email = self.conta_atual["email"]
            if any(r[0] == email and r[1] == self.pasta_exibida for r in resultados):
                i = self._indice_exibido()
                if i != wx.NOT_FOUND:
                    pasta = self.pastas_info[i]
                    self._mostrar_mensagens(pasta, self.cache.mensagens(email, pasta["raw"]), True)
        novas = [(email, n) for email, _, n in resultados if n > 0]
        if novas:
            self._avisar_novas(novas)

    def _avisar_novas(self, novas):
        def frase(n):
            return "1 nova mensagem" if n == 1 else f"{n} novas mensagens"
        if len(self.contas) == 1:
            texto = frase(novas[0][1])
        else:
            texto = "; ".join(f"{frase(n)} em {email}" for email, n in novas)
        self.SetStatusText(texto)
        if opcoes_dialog.opcao("avisar_com_som"):
            try:
                import winsound
                winsound.MessageBeep(winsound.MB_ICONASTERISK)
            except Exception:  # noqa: BLE001
                wx.Bell()
        if opcoes_dialog.opcao("avisar_com_janela"):
            avisar(texto, self)

    def abrir_opcoes(self):
        dlg = OpcoesDialog(self)
        if dlg.ShowModal() == wx.ID_OK:
            dlg.salvar()
            self._reiniciar_timer()
        dlg.Destroy()

    def mostrar_atalhos(self):
        dlg = AtalhosDialog(self)
        dlg.ShowModal()
        dlg.Destroy()

    def on_fechar(self, evento):
        self.timer_auto.Stop()
        evento.Skip()

    def _mostrar_mensagens(self, pasta, msgs, atualizado=False):
        """Mostra a lista. Se nada mudou, não mexe; se mudou, mantém a mensagem selecionada."""
        mesma_pasta = self.pasta_exibida == pasta["raw"]
        n = len(msgs)
        sufixo = "" if atualizado else " (cópia local)"
        self.SetStatusText(
            f"{pasta['nome']}: {n} mensagem{sufixo}" if n == 1
            else f"{pasta['nome']}: {n} mensagens{sufixo}")
        chave = lambda lista: [(m["uid"], m["lida"], m["assunto"]) for m in lista]  # noqa: E731
        if mesma_pasta and chave(self.mensagens) == chave(msgs):
            self.mensagens = msgs
            return
        selecionado, posicao = None, 0
        if mesma_pasta:
            posicao = self.lista.GetFirstSelected()
            if posicao != wx.NOT_FOUND and posicao < len(self.mensagens):
                selecionado = self.mensagens[posicao]["uid"]
            else:
                posicao = 0
        self.pasta_exibida = pasta["raw"]
        self.mensagens = msgs
        self.lista.DeleteAllItems()
        for i, m in enumerate(msgs):
            self.lista.InsertItem(i, texto_da_linha(m))
        if not msgs:
            return
        if selecionado is not None:  # mesma pasta: continua na mesma mensagem, se ela ainda existe
            destino = next((i for i, m in enumerate(msgs) if m["uid"] == selecionado),
                           min(posicao, n - 1))
        elif not mesma_pasta and not self.arvore.HasFocus():
            destino = 0
        else:
            return
        self.lista.Select(destino)
        self.lista.Focus(destino)
        self.lista.EnsureVisible(destino)

    # ---------- eventos ----------
    def on_verificar(self, evento):
        if not self.conta:
            return self.adicionar_conta()
        i = self._indice_exibido()
        if i == wx.NOT_FOUND:
            return self.conectar()
        self._carregar_pasta(i)

    def on_abrir(self, evento):
        i = evento.GetIndex()
        m = self.mensagens[i]
        pasta = self.pastas_info[self._indice_exibido()]
        self.SetStatusText("Abrindo mensagem...")
        if pasta["nome"] == "Rascunhos":
            return self._em_thread(
                lambda: self._obter_mensagem(pasta, m),
                lambda dados: self._editar_rascunho(pasta, m, dados),
            )
        self._em_thread(
            lambda: self._obter_mensagem(pasta, m),
            lambda dados: self._mostrar_mensagem(i, m, dados),
        )

    def _marcar_linha_lida(self, uid):
        """Mostra como lida a mensagem de UID dado, onde quer que ela esteja na lista agora."""
        for i, m in enumerate(self.mensagens):
            if m["uid"] == uid:
                m["lida"] = True
                self.lista.SetItemText(i, texto_da_linha(m))
                return

    def _mostrar_mensagem(self, i, m, dados):
        self._marcar_linha_lida(m["uid"])
        self.SetStatusText("")
        dlg = (WebMessageDialog if web_disponivel() else MessageDialog)(self, dados)
        dlg.ShowModal()
        acao = getattr(dlg, "acao", None)
        dlg.Destroy()
        self.lista.SetFocus()
        if acao:
            self.compor(self._preparar(acao, dados))

    def _preparar(self, acao, dados):
        """Dados da resposta; escreve a partir da conta que recebeu a mensagem, se for nossa."""
        de = self.conta["email"]
        if acao != "encaminhar":
            enderecos = {e.lower() for _, e in getaddresses([dados["para"], dados["cc"]])}
            de = next((c["email"] for c in self.contas if c["email"].lower() in enderecos), de)
        prefill = mailer.preparar(acao, dados, de)
        prefill["de_conta"] = de
        return prefill

    def _editar_rascunho(self, pasta, m, dados):
        self.SetStatusText("")
        prefill = mailer.de_rascunho(dados)
        prefill["rascunho"] = (self.conta["email"], pasta["raw"], m["uid"])
        prefill["de_conta"] = self.conta["email"]
        self.compor(prefill)

    # ---------- apagar, mover e marcar (uma ou várias mensagens) ----------
    def _selecao(self):
        """Mensagens selecionadas (Shift+setas, Ctrl+A...): (índices, mensagens, pasta)."""
        pasta = self._indice_exibido()
        indices, i = [], self.lista.GetFirstSelected()
        while i != wx.NOT_FOUND:
            if i < len(self.mensagens):
                indices.append(i)
            i = self.lista.GetNextSelected(i)
        if not indices or pasta == wx.NOT_FOUND:
            wx.MessageBox("Selecione uma ou mais mensagens na lista primeiro.", APP_NAME,
                          wx.OK | wx.ICON_INFORMATION, self)
            return None
        return indices, [self.mensagens[i] for i in indices], self.pastas_info[pasta]

    def _remover_linhas(self, indices):
        for i in sorted(indices, reverse=True):
            del self.mensagens[i]
            self.lista.DeleteItem(i)
        n = len(self.mensagens)
        if n:
            j = min(min(indices), n - 1)
            self.lista.Select(j)
            self.lista.Focus(j)
            self.lista.EnsureVisible(j)

    def _recarregar_atual(self, e):
        self._erro(e)
        i = self._indice_exibido()
        if i != wx.NOT_FOUND:
            self._carregar_pasta(i)

    def _em_lote(self, titulo, uids, operacao, texto_fim, pendentes=()):
        """Roda operacao(uids_do_lote) em partes, em segundo plano. Com várias mensagens
        mostra uma barra de progresso, que pode ser cancelada."""
        total, passo = len(uids), 5
        dlg = None
        if total > 1:
            dlg = wx.ProgressDialog(
                titulo, f"0 de {total}", maximum=total, parent=self,
                style=wx.PD_APP_MODAL | wx.PD_AUTO_HIDE | wx.PD_CAN_ABORT | wx.PD_ELAPSED_TIME,
            )
        cancelar = threading.Event()
        conta = self.conta
        self._pendentes.update(pendentes)

        def progresso(feitos):
            if dlg:
                cont, _ = dlg.Update(min(feitos, total), f"{feitos} de {total}")
                if not cont:
                    cancelar.set()

        def terminou(feitos, erro):
            self._pendentes.difference_update(pendentes)
            if dlg:
                dlg.Destroy()
            self.lista.SetFocus()
            if erro:
                self._recarregar_atual(erro)
            elif feitos < total:
                self.SetStatusText(f"Cancelado: {feitos} de {total} concluídas.")
                self._recarregar_atual_sem_erro()
            elif total > 1 and texto_fim:
                avisar(texto_fim, self)

        def corpo():
            _ctx.conta = conta
            feitos = 0
            try:
                for k in range(0, total, passo):
                    if cancelar.is_set():
                        break
                    lote = uids[k:k + passo]
                    operacao(lote)
                    feitos += len(lote)
                    wx.CallAfter(progresso, feitos)
            except Exception as e:  # noqa: BLE001
                wx.CallAfter(terminou, feitos, e)
                return
            wx.CallAfter(terminou, feitos, None)

        threading.Thread(target=corpo, daemon=True).start()

    def _recarregar_atual_sem_erro(self):
        i = self._indice_exibido()
        if i != wx.NOT_FOUND:
            self._carregar_pasta(i)

    def on_apagar(self, evento):
        """Delete: apaga a pasta se o foco está na lista de pastas, senão a mensagem."""
        if self.arvore.HasFocus():
            if self._pasta_selecionada() != wx.NOT_FOUND:
                self.apagar_pasta()
        else:
            self.apagar_mensagem()

    def on_apagar_de_vez(self, evento):
        """Shift+Delete: apaga as mensagens selecionadas sem passar pela Lixeira."""
        if self.arvore.HasFocus():
            if self._pasta_selecionada() != wx.NOT_FOUND:
                self.apagar_pasta()
        else:
            self.apagar_mensagem(de_vez=True)

    def apagar_mensagem(self, de_vez=False):
        sel = self._selecao()
        if not sel:
            return
        indices, msgs, pasta = sel
        n = len(msgs)
        lixeira = self._pasta_raw("Lixeira")
        definitivo = de_vez or pasta["nome"] == "Lixeira" or not lixeira or pasta["raw"] == lixeira
        perguntou = False
        if definitivo and opcoes_dialog.opcao("perguntar_apagar_de_vez"):
            perguntou = True
            texto = ("Apagar esta mensagem de vez? Ela não poderá ser recuperada." if n == 1 else
                     f"Apagar essas {n} mensagens de vez? Elas não poderão ser recuperadas.")
            dlg = wx.RichMessageDialog(self, texto, APP_NAME,
                                       wx.YES_NO | wx.NO_DEFAULT | wx.ICON_WARNING)
            dlg.ShowCheckBox("&Sempre perguntar antes de apagar de vez", True)
            r = dlg.ShowModal()
            if r == wx.ID_YES and not dlg.IsCheckBoxChecked():
                config.salvar_opcao("perguntar_apagar_de_vez", False)
            dlg.Destroy()
            if r != wx.ID_YES:
                return self.lista.SetFocus()
        self._remover_linhas(indices)
        self.cache.remover(self.conta["email"], pasta["raw"], [m["uid"] for m in msgs])
        fim = (f"{n} mensagens apagadas." if definitivo else f"{n} mensagens movidas para a Lixeira.")
        self.SetStatusText(
            "Mensagem apagada." if definitivo and n == 1 else
            "Mensagem movida para a Lixeira." if n == 1 else fim)
        op = ((lambda lote: self.imap.apagar_definitivo(pasta["raw"], lote)) if definitivo
              else (lambda lote: self.imap.mover(pasta["raw"], lote, lixeira)))
        # Sem confirmação (opção desligada), só a barra de progresso aparece, sem aviso no fim.
        self._em_lote("Apagando mensagens", [m["uid"] for m in msgs], op,
                      None if definitivo and not perguntou else fim,
                      [(self.conta["email"], pasta["raw"], m["uid"]) for m in msgs])

    def mover_mensagem(self):
        sel = self._selecao()
        if not sel:
            return
        indices, msgs, pasta = sel
        n = len(msgs)
        destinos = [p for p in self.pastas_info if p["raw"] != pasta["raw"]]
        dlg = wx.SingleChoiceDialog(
            self, "Escolha a pasta de destino:",
            "Mover mensagem" if n == 1 else f"Mover {n} mensagens", [p["nome"] for p in destinos])
        if dlg.ShowModal() != wx.ID_OK:
            dlg.Destroy()
            return self.lista.SetFocus()
        destino = destinos[dlg.GetSelection()]
        dlg.Destroy()
        self.lista.SetFocus()
        self._remover_linhas(indices)
        self.cache.remover(self.conta["email"], pasta["raw"], [m["uid"] for m in msgs])
        fim = (f"Mensagem movida para {destino['nome']}." if n == 1
               else f"{n} mensagens movidas para {destino['nome']}.")
        self.SetStatusText(fim)
        self._em_lote("Movendo mensagens", [m["uid"] for m in msgs],
                      lambda lote: self.imap.mover(pasta["raw"], lote, destino["raw"]), fim,
                      [(self.conta["email"], pasta["raw"], m["uid"]) for m in msgs])

    def marcar(self, lida):
        sel = self._selecao()
        if not sel:
            return
        indices, msgs, pasta = sel
        for i, m in zip(indices, msgs):
            m["lida"] = lida
            self.lista.SetItemText(i, texto_da_linha(m))
        self.cache.marcar_lida(self.conta["email"], pasta["raw"], [m["uid"] for m in msgs], lida)
        n = len(msgs)
        estado = "lida" if lida else "não lida"
        fim = f"Marcada como {estado}." if n == 1 else f"{n} mensagens marcadas como {estado}."
        self.SetStatusText(fim)
        self._em_lote("Marcando mensagens", [m["uid"] for m in msgs],
                      lambda lote: self.imap.marcar_lida(pasta["raw"], lote, lida), fim)

    def esvaziar_lixeira(self):
        """Arquivo > Esvaziar lixeira. A pergunta aparece sempre; a caixa de seleção liga ou
        desliga o aviso de Shift+Delete (a mesma opção de Ferramentas > Opções)."""
        if not self.conta:
            return
        lixeira = self._pasta_raw("Lixeira")
        if not lixeira:
            return wx.MessageBox("Não encontrei a lixeira desta conta.", APP_NAME,
                                 wx.OK | wx.ICON_WARNING, self)
        email = self.conta["email"]
        dlg = wx.RichMessageDialog(
            self, f"Esvaziar a lixeira de {email}? Todas as mensagens dela serão apagadas "
            "de vez e não poderão ser recuperadas.", APP_NAME,
            wx.YES_NO | wx.NO_DEFAULT | wx.ICON_WARNING)
        dlg.ShowCheckBox("&Sempre perguntar antes de apagar de vez", opcoes_dialog.opcao("perguntar_apagar_de_vez"))
        r = dlg.ShowModal()
        config.salvar_opcao("perguntar_apagar_de_vez", dlg.IsCheckBoxChecked())
        dlg.Destroy()
        if r != wx.ID_YES:
            return self.lista.SetFocus()
        self.SetStatusText("Esvaziando a lixeira...")

        def pronto(total):
            self.cache.esvaziar_pasta(email, lixeira)
            if self.conta_atual and self.conta_atual["email"] == email and self.pasta_exibida == lixeira:
                self.mensagens = []
                self.lista.DeleteAllItems()
            self.SetStatusText("Lixeira vazia.")
            avisar("A lixeira já estava vazia." if total == 0 else "Lixeira esvaziada.", self)
            self.lista.SetFocus()

        self._em_thread(lambda: self.imap.esvaziar_pasta(lixeira), pronto)

    # ---------- pastas ----------
    def nova_pasta(self):
        dlg = wx.TextEntryDialog(self, "Nome da nova pasta:", "Nova pasta")
        ok, nome = dlg.ShowModal() == wx.ID_OK, dlg.GetValue().strip()
        dlg.Destroy()
        if not ok or not nome:
            return self.arvore.SetFocus()
        self._em_thread(lambda: self.imap.criar_pasta(nome),
                        lambda raw: (self._recarregar_pastas(raw), avisar(f"Pasta {nome} criada.", self)))

    def _pasta_para_alterar(self):
        i = self._pasta_selecionada()
        if i == wx.NOT_FOUND:
            i = self._indice_exibido()
        if i == wx.NOT_FOUND:
            return None
        pasta = self.pastas_info[i]
        if pasta["protegida"]:
            wx.MessageBox(f"A pasta {pasta['nome']} é do sistema e não pode ser alterada.",
                          APP_NAME, wx.OK | wx.ICON_INFORMATION, self)
            return None
        return pasta

    def renomear_pasta(self):
        pasta = self._pasta_para_alterar()
        if not pasta:
            return
        atual = re.split(r"[/.]", pasta["decod"])[-1]
        dlg = wx.TextEntryDialog(self, "Novo nome da pasta:", "Renomear pasta", atual)
        ok, nome = dlg.ShowModal() == wx.ID_OK, dlg.GetValue().strip()
        dlg.Destroy()
        if not ok or not nome or nome == atual:
            return self.arvore.SetFocus()
        self._em_thread(lambda: self.imap.renomear_pasta(pasta["raw"], pasta["delim"], nome),
                        lambda raw: (self._recarregar_pastas(raw), avisar(f"Pasta renomeada para {nome}.", self)))

    def apagar_pasta(self):
        pasta = self._pasta_para_alterar()
        if not pasta:
            return
        r = wx.MessageBox(f"Apagar a pasta {pasta['nome']} e todas as mensagens dela?",
                          APP_NAME, wx.YES_NO | wx.NO_DEFAULT | wx.ICON_WARNING, self)
        if r != wx.YES:
            return self.arvore.SetFocus()
        self._em_thread(lambda: self.imap.apagar_pasta(pasta["raw"]),
                        lambda _: (self._recarregar_pastas(), avisar(f"Pasta {pasta['nome']} apagada.", self)))

    # ---------- escrever e enviar ----------
    def responder(self, acao):
        i = self.lista.GetFirstSelected()
        if i == wx.NOT_FOUND or not self.mensagens:
            return wx.MessageBox("Selecione uma mensagem na lista primeiro.", APP_NAME,
                                 wx.OK | wx.ICON_INFORMATION, self)
        m = self.mensagens[i]
        pasta = self.pastas_info[self._indice_exibido()]
        self.SetStatusText("Preparando mensagem...")

        def pronto(dados):
            self._marcar_linha_lida(m["uid"])
            self.SetStatusText("")
            self.compor(self._preparar(acao, dados))

        self._em_thread(lambda: self._obter_mensagem(pasta, m), pronto)

    def compor(self, prefill):
        if not self.contas:
            return self.adicionar_conta()
        dlg = ComposeDialog(self, prefill, [c["email"] for c in self.contas],
                            prefill.get("de_conta") or self.conta["email"])
        r = dlg.ShowModal()
        dados = dlg.dados()
        dados["rascunho"] = prefill.get("rascunho")
        dados["de_conta"] = dados["de_conta"] or self.conta["email"]
        dlg.Destroy()
        self.lista.SetFocus()
        if r == wx.ID_OK:
            self._enviar(dados)
        elif r == ID_RASCUNHO:
            self._salvar_rascunho(dados)

    def _aviso_leitor(self, texto):
        """Confirmação lida pelo leitor de tela; também aparece na barra de status."""
        self.SetStatusText(texto)
        avisar(texto, self)

    def _descartar_rascunho_antigo(self, dados):
        """Depois de enviar ou salvar um rascunho que veio do servidor, tira a versão antiga."""
        if dados.get("rascunho"):
            try:
                email, raw, uid = dados["rascunho"]
                dona = self._conta_por_email(email)
                self._cliente(dona).apagar_definitivo(raw, uid)
                self.cache.remover(email, raw, [uid])
            except Exception:  # noqa: BLE001 - o envio já deu certo; sobra só um rascunho velho
                pass

    def _obter_mensagem(self, pasta, m):
        """Texto completo da mensagem: da cópia local se já foi baixada, senão do servidor."""
        conta, raw, uid = self.conta["email"], pasta["raw"], m["uid"]
        conteudo = self.cache.corpo(conta, raw, uid)
        if conteudo is None:
            dados = self.imap.ler_mensagem(raw, uid)
            self.cache.guardar_corpo(conta, raw, uid, dados["raw"])
        else:
            dados = ImapClient.interpretar(conteudo)
            if not m["lida"]:
                try:
                    self.imap.marcar_lida(raw, uid, True)
                except Exception:  # noqa: BLE001 - sem conexão: a leitura continua funcionando
                    pass
        self.cache.marcar_lida(conta, raw, uid, True)
        return dados

    def _pasta_raw(self, nome, email=None):
        email = email or self.conta["email"]
        pastas = self.pastas_por_conta.get(email) or self.cache.pastas(email)
        return next((p["raw"] for p in pastas if p["nome"] == nome), None)

    def _enviar(self, dados):
        conta = self._conta_por_email(dados["de_conta"]) or self.conta
        if not conta.get("smtp_host"):
            wx.MessageBox("Falta o servidor SMTP. Complete em Ferramentas, Contas.", APP_NAME,
                          wx.OK | wx.ICON_WARNING, self)
            return self.compor(dados)
        self.SetStatusText("Enviando...")

        def trabalho():
            msg = mailer.montar(conta, dados)
            destinos = mailer.destinatarios(", ".join(
                dados[k] for k in ("para", "cc", "bcc") if dados[k]))
            mailer.enviar(conta, config.obter_senha(conta["email"]), msg, destinos)
            # A mensagem já foi enviada. O que vem agora é só arrumação: se falhar, não pode
            # aparecer como "não enviado" (o usuário reenviaria e o destinatário receberia duas vezes).
            try:
                self._descartar_rascunho_antigo(dados)
                # O Gmail já guarda a cópia em Enviados sozinho; os outros não.
                enviados = self._pasta_raw("Enviados", conta["email"])
                if enviados and "gmail" not in conta["host"]:
                    self._cliente(conta).guardar(
                        enviados, mailer.montar(conta, dados, True).as_bytes(), "(\\Seen)")
            except Exception:  # noqa: BLE001
                pass

        def falhou(e):
            self._erro(f"Não foi possível enviar. Sua mensagem foi mantida.\n{e}")
            self.compor(dados)

        self._em_thread_com_erro(trabalho, lambda _: self._aviso_leitor("E-mail enviado."), falhou)

    def _salvar_rascunho(self, dados):
        conta = self._conta_por_email(dados["de_conta"]) or self.conta
        rascunhos = self._pasta_raw("Rascunhos", conta["email"])
        if not rascunhos:
            self._erro("Não encontrei a pasta de rascunhos neste servidor.")
            return self.compor(dados)
        self.SetStatusText("Salvando rascunho...")
        def trabalho():
            self._cliente(conta).guardar(rascunhos, mailer.montar(conta, dados, True).as_bytes(),
                                         "(\\Draft)")
            self._descartar_rascunho_antigo(dados)

        self._em_thread_com_erro(
            trabalho,
            lambda _: self._aviso_leitor("Rascunho salvo."),
            lambda e: (self._erro(e), self.compor(dados)),
        )

    def abrir_catalogo(self):
        dlg = ContatosDialog(self)
        dlg.ShowModal()
        dlg.Destroy()
        self.arvore.SetFocus() if self.arvore.HasFocus() else self.lista.SetFocus()

    def salvar_remetente_selecionado(self):
        i = self.lista.GetFirstSelected()
        indice = self._indice_exibido()
        if i == wx.NOT_FOUND or i >= len(self.mensagens) or indice == wx.NOT_FOUND:
            return wx.MessageBox("Selecione uma mensagem na lista primeiro.", APP_NAME,
                                 wx.OK | wx.ICON_INFORMATION, self)
        m, pasta = self.mensagens[i], self.pastas_info[indice]
        self.SetStatusText("Lendo o remetente...")

        def pronto(dados):
            self._marcar_linha_lida(m["uid"])
            self.SetStatusText("")
            salvar_remetente(self, dados["de"])
            self.lista.SetFocus()

        self._em_thread(lambda: self._obter_mensagem(pasta, m), pronto)

    def on_sobre(self, evento):
        wx.MessageBox("Simple Email\nUm cliente de e-mail leve e acessível.\n"
                      "Pressione F1 para ver os atalhos de teclado.", "Sobre",
                      wx.OK | wx.ICON_INFORMATION, self)


def _registrar(texto):
    """Anota uma linha em erro.log (ajuda a descobrir por que uma conexão falhou)."""
    try:
        os.makedirs(config.PASTA, exist_ok=True)
        with open(os.path.join(config.PASTA, "erro.log"), "a", encoding="utf-8") as f:
            f.write(texto + "\n")
    except OSError:
        pass


def _registrar_erros():
    """Sem janela de terminal (pythonw), erros inesperados vão para erro.log."""
    arquivo = os.path.join(config.PASTA, "erro.log")

    def gancho(tipo, valor, tb):
        try:
            os.makedirs(config.PASTA, exist_ok=True)
            with open(arquivo, "a", encoding="utf-8") as f:
                f.write("".join(traceback.format_exception(tipo, valor, tb)) + "\n")
        except OSError:
            pass
        sys.__excepthook__(tipo, valor, tb)

    sys.excepthook = gancho
    threading.excepthook = lambda a: gancho(a.exc_type, a.exc_value, a.exc_traceback)


def main():
    _registrar_erros()
    app = wx.App(False)
    app.SetAppName(APP_NAME)
    MainFrame().Show()
    app.MainLoop()


if __name__ == "__main__":
    main()
