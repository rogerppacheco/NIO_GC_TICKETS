"""Modelos read-only das tabelas do app consulta-viabilidade-vtal (schema public)."""

from django.db import models


class VtalFonteDados(models.Model):
    codigo = models.CharField(max_length=20, unique=True)
    nome = models.CharField(max_length=255)
    ativa = models.BooleanField(default=True)
    ordem = models.PositiveSmallIntegerField(default=0)
    import_last_sheet_row_number = models.IntegerField(default=0)
    import_last_sheet_row_count = models.IntegerField(default=0)
    import_last_full_sync = models.DateTimeField(null=True, blank=True)

    class Meta:
        managed = False
        db_table = "viabilidade_fontedados"
        app_label = "tickets"
        ordering = ["ordem", "nome"]

    def __str__(self) -> str:
        return self.nome

    @property
    def is_mudanca(self) -> bool:
        return self.codigo == "mudanca"

    @property
    def is_nacional(self) -> bool:
        return self.codigo == "nacional"


class VtalDadosViabilidade(models.Model):
    fonte = models.ForeignKey(
        VtalFonteDados,
        on_delete=models.DO_NOTHING,
        related_name="viabilidades",
        db_column="fonte_id",
    )
    numero_linha_planilha = models.IntegerField(null=True, blank=True)
    carimbo_data_hora = models.DateTimeField(null=True, blank=True)
    email_solicitante = models.EmailField(null=True, blank=True)
    executivo_vendas = models.CharField(max_length=255, null=True, blank=True)
    nome_empresa_vendas_planilha = models.CharField(max_length=255, null=True, blank=True)
    numero_protocolo = models.CharField(max_length=255, null=True, blank=True)
    matricula_solicitante = models.CharField(max_length=255, null=True, blank=True)
    operacao = models.CharField(max_length=255, null=True, blank=True)
    nome_eps = models.CharField(max_length=255, null=True, blank=True)
    tipo_produto = models.CharField(max_length=255, null=True, blank=True)
    estado_uf = models.TextField(null=True, blank=True)
    cep = models.TextField(null=True, blank=True)
    cep_normalizado = models.CharField(max_length=16, null=True, blank=True)
    cidade = models.TextField(null=True, blank=True)
    tipo_logradouro = models.TextField(null=True, blank=True)
    logradouro = models.TextField(null=True, blank=True)
    numero_fachada = models.TextField(null=True, blank=True)
    fachada_normalizada = models.CharField(max_length=64, null=True, blank=True)
    bairro = models.TextField(null=True, blank=True)
    complemento = models.TextField(null=True, blank=True)
    observacoes_vendas = models.TextField(null=True, blank=True)
    status_tratamento = models.TextField(null=True, blank=True)
    observacoes_vtal = models.TextField(null=True, blank=True)
    data_evento_vtal = models.DateField(null=True, blank=True)
    horario_fechamento_vtal = models.TimeField(null=True, blank=True)

    class Meta:
        managed = False
        db_table = "viabilidade_dadosviabilidade"
        app_label = "tickets"
        ordering = ["-carimbo_data_hora", "-id"]

    def __str__(self) -> str:
        return f"CEP {self.cep} · nº {self.numero_fachada}"


class VtalSystemStatus(models.Model):
    """Status da importação Google Sheets no app consulta-viabilidade-vtal."""

    import_end_time = models.DateTimeField(null=True, blank=True)
    import_last_full_sync = models.DateTimeField(null=True, blank=True)

    class Meta:
        managed = False
        db_table = "viabilidade_systemstatus"
        app_label = "tickets"

    def __str__(self) -> str:
        return "Status da importação VTAL"
