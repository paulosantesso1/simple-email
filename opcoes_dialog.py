"""Janelas de Opções e de ajuda com os atalhos de teclado."""
import wx

import config

PADROES = {
    "intervalo_verificacao": 5,
    "avisar_com_som": True,
    "avisar_com_janela": True,
    "avisar_com_notificacao": True,
    "perguntar_apagar_de_vez": True,
    "agrupar_mensagens": False,
    "ordem_conversa": "antigas",
}

ORDENS = (("antigas", "Da mais antiga para a mais nova"),
          ("novas", "Da mais nova para a mais antiga"))

ATALHOS = """\
GERAL
F5 ..... verificar e-mails
Ctrl+N ..... nova mensagem
Ctrl+PgDn / Ctrl+PgUp ..... próxima conta / conta anterior
F1 ..... esta lista de atalhos

NA ÁRVORE DE CONTAS E PASTAS
Seta direita ou Enter ..... abrir a conta e ver as pastas
Seta esquerda ..... recolher
Enter numa pasta ..... ir para as mensagens
F2 ..... renomear pasta
Delete ..... apagar pasta

NA LISTA DE MENSAGENS
Enter ..... abrir a mensagem (Esc fecha e volta para a lista)
Shift+setas, Ctrl+A ..... selecionar várias
Delete ..... mover para a Lixeira
Shift+Delete ..... apagar de vez
Ctrl+Shift+M ..... mover para outra pasta
Ctrl+Q / Ctrl+U ..... marcar como lida / não lida
Ctrl+R ..... responder
Ctrl+Shift+R ..... responder a todos
Ctrl+L ..... encaminhar
Ctrl+Shift+A ..... salvar remetente como contato
Tecla Aplicativos ou Shift+F10 ..... menu da mensagem (abrir, responder, apagar...)
Com o agrupamento ligado (Ferramentas, Opções), uma conversa é uma linha só: Enter abre
todas as mensagens dela numa página, e Delete, mover e marcar valem para a conversa inteira

NA JANELA DA MENSAGEM
H, K e as outras teclas de navegação do NVDA funcionam no texto
Ctrl+R, Ctrl+Shift+R, Ctrl+L ..... responder, responder a todos, encaminhar
Esc ..... fechar

AO ESCREVER
Ctrl+Enter ..... enviar
Ctrl+S ..... salvar rascunho
Ctrl+K ..... catálogo de endereços
Esc ..... fechar (pergunta se quiser salvar o rascunho)
"""


def opcao(chave):
    return config.opcao(chave, PADROES[chave])


class OpcoesDialog(wx.Dialog):
    def __init__(self, parent):
        super().__init__(parent, title="Opções")
        r1 = wx.StaticText(self, label="Verificar e-mails &automaticamente a cada (minutos, 0 desliga):")
        self.intervalo = wx.SpinCtrl(self, min=0, max=1440, initial=int(opcao("intervalo_verificacao")),
                                     name="Minutos entre as verificações")
        self.som = wx.CheckBox(self, label="Tocar um &som quando chegar e-mail novo")
        self.som.SetValue(bool(opcao("avisar_com_som")))
        self.janela = wx.CheckBox(
            self, label="Mostrar um &aviso, lido pelo leitor de tela, quando chegar e-mail novo")
        self.janela.SetValue(bool(opcao("avisar_com_janela")))
        self.notificacao = wx.CheckBox(
            self, label="Mostrar os avisos (e-mail enviado, rascunho salvo...) como &notificação "
            "do sistema, sem pausar a navegação")
        self.notificacao.SetValue(bool(opcao("avisar_com_notificacao")))
        self.perguntar = wx.CheckBox(self, label="&Perguntar antes de apagar mensagens de vez")
        self.perguntar.SetValue(bool(opcao("perguntar_apagar_de_vez")))
        self.agrupar = wx.CheckBox(
            self, label="A&grupar mensagens da mesma conversa numa linha só")
        self.agrupar.SetValue(bool(opcao("agrupar_mensagens")))
        r2 = wx.StaticText(self, label="&Ordem das mensagens dentro de uma conversa agrupada:")
        self.ordem = wx.Choice(self, choices=[t for _, t in ORDENS],
                               name="Ordem das mensagens agrupadas")
        atual = opcao("ordem_conversa")
        self.ordem.SetSelection(next((i for i, (k, _) in enumerate(ORDENS) if k == atual), 0))

        raiz = wx.BoxSizer(wx.VERTICAL)
        raiz.Add(r1, 0, wx.LEFT | wx.RIGHT | wx.TOP, 12)
        raiz.Add(self.intervalo, 0, wx.ALL, 12)
        for c in (self.som, self.janela, self.notificacao, self.perguntar, self.agrupar):
            raiz.Add(c, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 12)
        raiz.Add(r2, 0, wx.LEFT | wx.RIGHT, 12)
        raiz.Add(self.ordem, 0, wx.ALL, 12)
        raiz.Add(self.CreateStdDialogButtonSizer(wx.OK | wx.CANCEL), 0, wx.ALL | wx.ALIGN_RIGHT, 12)
        self.SetSizerAndFit(raiz)
        self.intervalo.SetFocus()

    def salvar(self):
        config.salvar_opcao("intervalo_verificacao", self.intervalo.GetValue())
        config.salvar_opcao("avisar_com_som", self.som.GetValue())
        config.salvar_opcao("avisar_com_janela", self.janela.GetValue())
        config.salvar_opcao("avisar_com_notificacao", self.notificacao.GetValue())
        config.salvar_opcao("perguntar_apagar_de_vez", self.perguntar.GetValue())
        config.salvar_opcao("agrupar_mensagens", self.agrupar.GetValue())
        config.salvar_opcao("ordem_conversa", ORDENS[self.ordem.GetSelection()][0])


class AtalhosDialog(wx.Dialog):
    def __init__(self, parent):
        super().__init__(parent, title="Atalhos de teclado", size=(640, 560),
                         style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
        rotulo = wx.StaticText(self, label="&Atalhos")
        texto = wx.TextCtrl(self, value=ATALHOS, name="Atalhos",
                            style=wx.TE_MULTILINE | wx.TE_READONLY | wx.TE_RICH2)
        fechar = wx.Button(self, wx.ID_CANCEL, "&Fechar")
        raiz = wx.BoxSizer(wx.VERTICAL)
        raiz.Add(rotulo, 0, wx.ALL, 8)
        raiz.Add(texto, 1, wx.EXPAND | wx.LEFT | wx.RIGHT, 8)
        raiz.Add(fechar, 0, wx.ALL | wx.ALIGN_RIGHT, 8)
        self.SetSizer(raiz)
        self.SetEscapeId(wx.ID_CANCEL)
        texto.SetInsertionPoint(0)
        texto.SetFocus()
