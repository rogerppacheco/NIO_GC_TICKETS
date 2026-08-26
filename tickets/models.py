from __future__ import annotations

from decimal import Decimal

from django.conf import settings
from django.db import models, transaction
from django.db.models import Max
from django.utils import timezone


class Parceiro(models.Model):
    codigo_pdv = models.CharField("Código PDV", max_length=32, unique=True)
    nome = models.CharField("Nome", max_length=120)
    contato_nome = models.CharField(
        "Contato principal (legado)",
        max_length=120,
        blank=True,
        help_text="Preferir cadastro em Contatos do PDV.",
    )
    email = models.EmailField(blank=True)
    telefone = models.CharField(max_length=40, blank=True)
    ativo = models.BooleanField(default=True)
    especialista = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="parceiros_especialista",
        verbose_name="Especialista",
        help_text="Responsável NIO por este PDV. Vê e trata as demandas deste parceiro.",
    )
    token_acesso = models.CharField(
        max_length=64,
        blank=True,
        help_text="Um único token para todos os contatos deste PDV (opcional).",
    )
    criado_em = models.DateTimeField(auto_now_add=True)
    atualizado_em = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["nome"]
        verbose_name = "Parceiro"
        verbose_name_plural = "Parceiros"

    def __str__(self) -> str:
        return f"{self.codigo_pdv} - {self.nome}"


class ContatoParceiro(models.Model):
    """Pessoa autorizada a abrir demandas em nome do PDV."""

    parceiro = models.ForeignKey(
        Parceiro, on_delete=models.CASCADE, related_name="contatos"
    )
    nome = models.CharField(max_length=120)
    email = models.EmailField(blank=True)
    telefone = models.CharField("WhatsApp / telefone", max_length=40, blank=True)
    cargo = models.CharField(max_length=80, blank=True)
    token_acesso = models.CharField(
        max_length=64,
        blank=True,
        help_text="Legado — o portal usa apenas o token do PDV.",
    )
    ativo = models.BooleanField(default=True)
    criado_em = models.DateTimeField(auto_now_add=True)
    atualizado_em = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["nome"]
        verbose_name = "Contato do parceiro"
        verbose_name_plural = "Contatos do parceiro"
        constraints = [
            models.UniqueConstraint(
                fields=["parceiro", "nome"],
                name="uniq_contato_nome_por_parceiro",
            )
        ]

    def __str__(self) -> str:
        return f"{self.nome} ({self.parceiro.codigo_pdv})"


class TipoDemanda(models.TextChoices):
    AGENDAR_REAGENDAR = "agendar_reagendar", "Agendar/Reagendar pedido (7095, 7029, 7037)"
    ENDERECO_DOC = "endereco_doc", "Endereço do Pedido"
    STATUS_PEDIDO = "status_pedido", "Status do pedido - agendamento atual"
    PRIORIDADE_ELITE = "prioridade_elite", "Prioridade na instalação (Grupo Elite)"
    RESET_SENHA = "reset_senha", "Reset de senha"
    VIABILIDADE = "viabilidade", "Consulta de viabilidade (sistema fora)"
    ACESSO_APP = "acesso_app", "Chamado acesso App NIO"
    ABRIR_CHAMADO_TI = "abrir_chamado_ti", "Abrir chamado com TI"
    SEM_SLOT = "sem_slot", "Sinalização — sem slot / liberação de agenda"
    INSTALACAO_FISICA = "instalacao_fisica", "Sinalização — instalação física / pendência"
    REPARO = "reparo", "Reparo — internet pós-instalação (até 14 dias)"
    OUTROS = "outros", "Outros / suporte geral"


class StatusTicket(models.TextChoices):
    NOVO = "novo", "Novo"
    EM_ANALISE = "em_analise", "Em análise"
    AGUARDANDO_PARCEIRO = "aguardando_parceiro", "Aguardando parceiro"
    ENCAMINHADO = "encaminhado", "Encaminhado"
    RESOLVIDO = "resolvido", "Resolvido"
    FECHADO = "fechado", "Fechado"
    CANCELADO = "cancelado", "Cancelado"


class Prioridade(models.TextChoices):
    BAIXA = "baixa", "Baixa"
    NORMAL = "normal", "Normal"
    ALTA = "alta", "Alta"
    URGENTE = "urgente", "Urgente"


class Turno(models.TextChoices):
    MANHA = "manha", "Manhã"
    TARDE = "tarde", "Tarde"
    INTEGRAL = "integral", "Integral / indiferente"


class Ticket(models.Model):
    protocolo = models.CharField(max_length=20, unique=True, editable=False)
    parceiro = models.ForeignKey(
        Parceiro, on_delete=models.PROTECT, related_name="tickets"
    )
    contato = models.ForeignKey(
        "ContatoParceiro",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="tickets",
        verbose_name="Contato que abriu",
    )
    tipo = models.CharField(max_length=40, choices=TipoDemanda.choices)
    status = models.CharField(
        max_length=30, choices=StatusTicket.choices, default=StatusTicket.NOVO, db_index=True
    )
    prioridade = models.CharField(
        max_length=20, choices=Prioridade.choices, default=Prioridade.NORMAL
    )

    # Campos comuns / melhorias vs Forms
    solicitante_nome = models.CharField("Quem solicita", max_length=120, blank=True)
    solicitante_contato = models.CharField("Telefone/WhatsApp", max_length=60, blank=True)
    pedido = models.CharField("Pedido / OS", max_length=80, blank=True)
    pedidos_extras = models.TextField(
        "Pedidos adicionais",
        blank=True,
        help_text="Um por linha — melhoria vs Forms (só 1 pedido).",
    )
    documento_cliente = models.CharField("CPF/CNPJ", max_length=20, blank=True)
    tt = models.CharField("TT", max_length=80, blank=True)
    tt_vendedor = models.CharField("TT do vendedor", max_length=80, blank=True)
    tt_backoffice = models.CharField(
        "TT do backoffice de cadastro",
        max_length=80,
        blank=True,
        help_text="TT do backoffice de cadastro do pedido com problema.",
    )
    cep = models.CharField("CEP", max_length=12, blank=True)
    logradouro = models.CharField("Logradouro", max_length=180, blank=True)
    numero_fachada = models.CharField("Nº fachada", max_length=40, blank=True)
    complemento = models.CharField("Complemento", max_length=80, blank=True)
    bairro = models.CharField("Bairro", max_length=120, blank=True)
    cidade = models.CharField("Cidade", max_length=120, blank=True)
    uf = models.CharField("UF", max_length=2, blank=True)
    endereco_completo = models.CharField(
        "Endereço completo",
        max_length=255,
        blank=True,
        help_text="Montado automaticamente pelo ViaCEP + nº/complemento.",
    )
    data_desejada = models.DateField("Data desejada", null=True, blank=True)
    turno = models.CharField(max_length=20, choices=Turno.choices, blank=True)
    nome_cliente = models.CharField("Nome do cliente", max_length=180, blank=True)
    data_instalacao = models.DateField("Data da instalação", null=True, blank=True)
    data_alternativa = models.DateField(
        "Opção 2 — Data",
        null=True,
        blank=True,
        help_text="Segunda opção de data para retorno do técnico (reparo).",
    )
    turno_alternativo = models.CharField(
        "Opção 2 — Turno",
        max_length=20,
        choices=Turno.choices,
        blank=True,
    )
    descricao = models.TextField("Descrição detalhada", blank=True)
    observacoes = models.TextField(blank=True)

    # Tratamento (espelha planilha: STATUS / RETORNO / DETALHES)
    resultado_status = models.CharField(
        "STATUS",
        max_length=255,
        blank=True,
        help_text="Resumo operacional (ex.: SOLICITADA PRIORIDADE, AGENDAMENTO CANCELADO...).",
        db_index=True,
    )
    retorno_dados = models.JSONField(
        "Dados do retorno",
        default=dict,
        blank=True,
        help_text="Campos estruturados da resposta (senha, endereço consultado, etc.).",
    )
    resposta_publica = models.TextField(
        "RETORNO",
        blank=True,
        help_text="Texto de retorno ao parceiro / registro do que foi feito.",
    )
    nota_interna = models.TextField(
        "DETALHES",
        blank=True,
        help_text="Detalhes internos de acompanhamento (não necessariamente público).",
    )
    destino_encaminhamento = models.CharField(max_length=120, blank=True)
    atendente = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="tickets_atendidos",
    )

    criado_em = models.DateTimeField(auto_now_add=True, db_index=True)
    atualizado_em = models.DateTimeField(auto_now=True)
    primeiro_atendimento_em = models.DateTimeField(null=True, blank=True)
    resolvido_em = models.DateTimeField(null=True, blank=True)
    resposta_iniciada_em = models.DateTimeField(
        "Início do tratamento",
        null=True,
        blank=True,
        help_text="Momento em que o atendente clicou em Responder.",
    )
    resposta_salva_em = models.DateTimeField(
        "Fim do tratamento",
        null=True,
        blank=True,
        help_text="Momento em que a resposta foi salva.",
    )
    tempo_retorno_segundos = models.PositiveIntegerField(
        "Retorno de tratamento (s)",
        null=True,
        blank=True,
        help_text="Tempo entre clicar em Responder e Salvar resposta (primeira vez).",
    )

    class Meta:
        ordering = ["-criado_em"]
        indexes = [
            models.Index(fields=["status", "-criado_em"]),
            models.Index(fields=["tipo", "status"]),
        ]

    def __str__(self) -> str:
        return f"{self.protocolo} · {self.get_tipo_display()}"

    @staticmethod
    def gerar_protocolo() -> str:
        ano = timezone.localtime().year
        prefix = f"{ano}-"
        with transaction.atomic():
            ultimo = (
                Ticket.objects.select_for_update()
                .filter(protocolo__startswith=prefix)
                .aggregate(Max("protocolo"))
                .get("protocolo__max")
            )
            seq = 1
            if ultimo:
                try:
                    seq = int(ultimo.split("-", 1)[1]) + 1
                except (IndexError, ValueError):
                    seq = Ticket.objects.filter(protocolo__startswith=prefix).count() + 1
            return f"{prefix}{seq:04d}"

    def montar_endereco(self) -> str:
        parts = []
        if self.logradouro:
            parts.append(self.logradouro.strip())
        if self.numero_fachada:
            parts.append(str(self.numero_fachada).strip())
        if self.complemento:
            parts.append(self.complemento.strip())
        loc = ""
        if self.bairro:
            loc = self.bairro.strip()
        if self.cidade:
            loc = f"{loc}, {self.cidade.strip()}" if loc else self.cidade.strip()
        if self.uf:
            uf = self.uf.strip().upper()
            loc = f"{loc} - {uf}" if loc else uf
        if loc:
            parts.append(loc)
        if self.cep:
            parts.append(self.cep.strip())
        return ", ".join(p for p in parts if p)

    def save(self, *args, **kwargs):
        if not self.protocolo:
            self.protocolo = self.gerar_protocolo()
        montado = self.montar_endereco()
        if montado:
            self.endereco_completo = montado
        if self.status in {StatusTicket.RESOLVIDO, StatusTicket.FECHADO} and not self.resolvido_em:
            self.resolvido_em = timezone.now()
        super().save(*args, **kwargs)

    @property
    def sla_minutos(self) -> float | None:
        if not self.primeiro_atendimento_em:
            return None
        delta = self.primeiro_atendimento_em - self.criado_em
        return round(delta.total_seconds() / 60, 1)

    @property
    def tempo_retorno_tratamento(self) -> str:
        return formatar_duracao(self.tempo_retorno_segundos)

    def iniciar_tratamento(self, user) -> None:
        """Abre o modal e inicia o cronômetro. Não muda a situação na fila."""
        agora = timezone.now()
        campos = ["resposta_iniciada_em", "atualizado_em"]
        self.resposta_iniciada_em = agora
        if not self.atendente and user is not None:
            self.atendente = user
            campos.append("atendente")
        self.save(update_fields=campos)

    def registrar_tempo_resposta(self) -> None:
        agora = timezone.now()
        self.resposta_salva_em = agora
        if self.tempo_retorno_segundos is None and self.resposta_iniciada_em:
            delta = agora - self.resposta_iniciada_em
            self.tempo_retorno_segundos = max(0, int(delta.total_seconds()))

    @property
    def aberto(self) -> bool:
        return self.status not in {
            StatusTicket.RESOLVIDO,
            StatusTicket.FECHADO,
            StatusTicket.CANCELADO,
        }


class Mensagem(models.Model):
    ticket = models.ForeignKey(Ticket, on_delete=models.CASCADE, related_name="mensagens")
    autor = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL
    )
    autor_nome = models.CharField(max_length=120, blank=True)
    interno = models.BooleanField(
        default=False, help_text="Se marcado, não aparece para o parceiro."
    )
    corpo = models.TextField()
    criado_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["criado_em"]

    def __str__(self) -> str:
        return f"Msg {self.ticket.protocolo} @ {self.criado_em:%d/%m %H:%M}"


class Anexo(models.Model):
    ticket = models.ForeignKey(Ticket, on_delete=models.CASCADE, related_name="anexos")
    arquivo = models.FileField(upload_to="anexos/%Y/%m/")
    nome_original = models.CharField(max_length=255, blank=True)
    enviado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL
    )
    criado_em = models.DateTimeField(auto_now_add=True)

    def __str__(self) -> str:
        return self.nome_original or self.arquivo.name

    @property
    def eh_imagem(self) -> bool:
        nome = f"{self.nome_original or ''} {getattr(self.arquivo, 'name', '') or ''}".lower()
        return any(nome.endswith(ext) for ext in (".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp"))

    def url_arquivo(self) -> str:
        try:
            return self.arquivo.url
        except Exception:
            return ""


class Mascara(models.Model):
    """Templates padrão para encaminhar a outras áreas (ex.: Grupo Elite)."""

    nome = models.CharField(max_length=120)
    destino = models.CharField(
        max_length=120,
        help_text="Ex.: Grupo Elite, BO Agendamento, Suporte App",
    )
    tipos = models.CharField(
        max_length=255,
        blank=True,
        help_text="Códigos de tipo separados por vírgula; vazio = todos.",
    )
    template = models.TextField(
        help_text=(
            "Variáveis: {{protocolo}} {{parceiro}} {{pdv}} {{tipo}} {{pedido}} "
            "{{documento}} {{endereco}} {{cep}} {{fachada}} {{data}} {{turno}} "
            "{{data_2}} {{turno_2}} {{nome_cliente}} {{data_instalacao}} {{nome_gc}} "
            "{{descricao}} {{observacoes}} {{solicitante}} {{contato}} {{tt}} "
            "{{tt_vendedor}} {{tt_backoffice}} {{os}}"
        )
    )
    ativo = models.BooleanField(default=True)
    criado_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["nome"]
        verbose_name = "Máscara"
        verbose_name_plural = "Máscaras"

    def __str__(self) -> str:
        return self.nome

    def aplica_para(self, tipo: str) -> bool:
        if not self.tipos.strip():
            return True
        allowed = {t.strip() for t in self.tipos.split(",") if t.strip()}
        return tipo in allowed


class ConfigRespostaTipo(models.Model):
    """Campos de resposta exibidos ao tratar cada tipo de demanda."""

    tipo = models.CharField(
        max_length=40, unique=True, choices=TipoDemanda.choices, db_index=True
    )
    campos = models.JSONField(
        default=list,
        blank=True,
        help_text="Lista de campos: name, label, widget, required, ativo, help, placeholder.",
    )
    atualizado_em = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["tipo"]
        verbose_name = "Config. resposta por tipo"
        verbose_name_plural = "Configs resposta por tipo"

    def __str__(self) -> str:
        return self.get_tipo_display()

    def campos_ativos(self) -> list[dict]:
        return [c for c in (self.campos or []) if c.get("ativo", True)]


class PerfilStaff(models.Model):
    class Papel(models.TextChoices):
        GESTOR = "gestor", "Admin"
        ESPECIALISTA = "especialista", "Especialista"

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="perfil_staff",
    )
    papel = models.CharField(
        max_length=20,
        choices=Papel.choices,
        default=Papel.ESPECIALISTA,
        db_index=True,
    )
    fte = models.DecimalField(
        "FTE",
        max_digits=3,
        decimal_places=2,
        default=Decimal("1.00"),
        help_text="1.00 representa tempo integral e 0.5 representa meio período.",
    )
    whatsapp = models.CharField(
        "WhatsApp",
        max_length=40,
        blank=True,
        help_text="Número com DDI para receber as máscaras (especialista). Ex.: 5531999999999.",
    )

    class Meta:
        verbose_name = "Perfil interno"
        verbose_name_plural = "Perfis internos"

    def __str__(self) -> str:
        return f"{self.user} · {self.get_papel_display()}"


def formatar_duracao(segundos: int | None) -> str:
    if segundos is None:
        return "—"
    segundos = max(0, int(segundos))
    horas, resto = divmod(segundos, 3600)
    minutos, segs = divmod(resto, 60)
    if horas:
        return f"{horas}h {minutos:02d}min"
    if minutos:
        return f"{minutos}min {segs:02d}s" if segs else f"{minutos} min"
    return f"{segs}s"


class Encaminhamento(models.Model):
    ticket = models.ForeignKey(
        Ticket, on_delete=models.CASCADE, related_name="encaminhamentos"
    )
    mascara = models.ForeignKey(
        Mascara, null=True, blank=True, on_delete=models.SET_NULL
    )
    destino = models.CharField(max_length=120)
    conteudo = models.TextField()
    criado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL
    )
    criado_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-criado_em"]
