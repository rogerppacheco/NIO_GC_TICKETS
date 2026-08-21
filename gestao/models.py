from __future__ import annotations

from django.conf import settings
from django.db import models


class GestaoConfig(models.Model):
    chave = models.CharField(max_length=80, unique=True)
    valor = models.CharField(max_length=500, blank=True)

    class Meta:
        verbose_name = "Configuração de gestão"
        verbose_name_plural = "Configurações de gestão"

    def __str__(self) -> str:
        return f"{self.chave}={self.valor}"


class LoteImportacao(models.Model):
    class Tipo(models.TextChoices):
        SYSMAP = "sysmap", "Sysmap / Supply"
        OSAB = "osab", "OSAB"
        FPD = "fpd", "FPD"
        CHURN = "churn", "Churn"
        COMISSIONAMENTO = "comissionamento", "Comissionamento"
        TAREFAS = "tarefas", "Tarefas"
        VENDA_INDEVIDA = "venda_indevida", "Venda indevida"
        RECOMPRA = "recompra", "Recompra"

    tipo = models.CharField(max_length=20, choices=Tipo.choices, db_index=True)
    arquivo_nome = models.CharField(max_length=255)
    ok = models.BooleanField(default=True)
    erro = models.TextField(blank=True)
    resumo = models.JSONField(default=dict, blank=True)
    criado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="lotes_gestao",
    )
    criado_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-criado_em"]
        verbose_name = "Lote de importação"
        verbose_name_plural = "Lotes de importação"

    def __str__(self) -> str:
        return f"{self.get_tipo_display()} · {self.arquivo_nome}"


class CadastroTerceiro(models.Model):
    chave_acesso = models.CharField(max_length=50, unique=True, db_index=True)
    nome_terceiro = models.CharField(max_length=200, blank=True)
    cpf = models.CharField(max_length=30, blank=True)
    email = models.CharField(max_length=200, blank=True)
    razao_social = models.CharField(max_length=200, blank=True, db_index=True)
    parceiro = models.ForeignKey(
        "tickets.Parceiro",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="terceiros",
    )
    vinculo = models.CharField(max_length=50, blank=True)
    cargo_funcao = models.CharField(max_length=100, blank=True)
    situacao_empresa = models.CharField(max_length=50, blank=True)
    situacao_funcional = models.CharField(max_length=80, blank=True)
    situacao_contrato = models.CharField(max_length=50, blank=True)
    data_alocacao = models.DateField(null=True, blank=True)
    data_desalocacao = models.DateField(null=True, blank=True)
    data_inativacao = models.DateField(null=True, blank=True)
    ativo = models.BooleanField(default=False, db_index=True)
    data_referencia = models.DateField(null=True, blank=True)
    data_importacao = models.DateTimeField(auto_now_add=True)
    data_atualizacao = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["nome_terceiro", "chave_acesso"]
        verbose_name = "Terceiro (Sysmap)"
        verbose_name_plural = "Terceiros (Sysmap)"

    def __str__(self) -> str:
        return f"{self.chave_acesso} · {self.nome_terceiro}"


class VendaOSAB(models.Model):
    pedido = models.CharField(max_length=100, unique=True, db_index=True)
    dt_ref = models.DateTimeField(null=True, blank=True, db_index=True)
    matricula_vendedor = models.CharField(max_length=100, blank=True, db_index=True)
    nome_vendedor = models.CharField(max_length=200, blank=True)
    pdv_nome = models.CharField(max_length=150, db_index=True)
    parceiro = models.ForeignKey(
        "tickets.Parceiro",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="vendas_osab",
    )
    data_abertura = models.DateTimeField(null=True, blank=True, db_index=True)
    data_fechamento = models.DateTimeField(null=True, blank=True)
    situacao = models.CharField(max_length=200, blank=True)
    velocidade = models.CharField(max_length=100, blank=True)
    meio_pagamento = models.CharField(max_length=100, blank=True)
    data_importacao = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-data_abertura"]
        verbose_name = "Venda OSAB"
        verbose_name_plural = "Vendas OSAB"

    def __str__(self) -> str:
        return self.pedido


class AnaliseCapilaridade(models.Model):
    data_analise = models.DateField()
    ano_referencia = models.IntegerField(db_index=True)
    mes_referencia = models.IntegerField(db_index=True)
    matricula_vendedor = models.CharField(max_length=100, db_index=True)
    nome_vendedor = models.CharField(max_length=200, blank=True)
    pdv_nome = models.CharField(max_length=150, db_index=True)
    parceiro = models.ForeignKey(
        "tickets.Parceiro",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="analises_capilaridade",
    )
    dias_sem_vender = models.IntegerField(null=True, blank=True)
    status = models.CharField(max_length=50)
    ultima_venda = models.DateTimeField(null=True, blank=True)
    sem_venda_osab = models.BooleanField(default=False)

    class Meta:
        ordering = ["pdv_nome", "matricula_vendedor"]
        indexes = [
            models.Index(fields=["ano_referencia", "mes_referencia"]),
        ]
        verbose_name = "Análise de capilaridade"
        verbose_name_plural = "Análises de capilaridade"


class MetaCapilaridade(models.Model):
    parceiro = models.ForeignKey(
        "tickets.Parceiro",
        on_delete=models.CASCADE,
        related_name="metas_capilaridade",
    )
    ano = models.IntegerField()
    mes = models.IntegerField()
    meta_vendedores = models.IntegerField(default=0)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["parceiro", "ano", "mes"],
                name="uniq_meta_cap_parceiro_periodo",
            )
        ]
        verbose_name = "Meta de capilaridade"
        verbose_name_plural = "Metas de capilaridade"


class ConfiguracaoOSAB(models.Model):
    parceiro = models.ForeignKey(
        "tickets.Parceiro",
        on_delete=models.CASCADE,
        related_name="configs_osab",
    )
    ano = models.IntegerField()
    mes = models.IntegerField()
    meta_vl = models.IntegerField(default=0)
    du_vl = models.FloatField(default=0)
    meta_gross = models.IntegerField(default=0)
    du_gross = models.FloatField(default=0)
    pesos_diarios_vl = models.TextField(blank=True)
    pesos_diarios_gross = models.TextField(blank=True)
    comissao_500 = models.IntegerField(default=0)
    comissao_700 = models.IntegerField(default=0)
    comissao_1000 = models.IntegerField(default=0)
    tem_bonus = models.BooleanField(default=False)
    comissao_bonus = models.IntegerField(default=0)
    tem_bonus_m10 = models.BooleanField(default=False)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["parceiro", "ano", "mes"],
                name="uniq_config_osab_parceiro_periodo",
            )
        ]
        verbose_name = "Configuração OSAB"
        verbose_name_plural = "Configurações OSAB"


class HistoricoOSAB(models.Model):
    data_processamento = models.DateTimeField(auto_now_add=True, db_index=True)
    parceiro = models.ForeignKey(
        "tickets.Parceiro",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="historicos_osab",
    )
    descricao_pdv = models.CharField(max_length=150)
    status = models.CharField(max_length=50, default="Ok")
    detalhes = models.JSONField(default=dict, blank=True)
    realizado_vl = models.FloatField(null=True, blank=True)
    atingimento_vl = models.FloatField(null=True, blank=True)
    realizado_gross = models.IntegerField(null=True, blank=True)
    atingimento_gross = models.FloatField(null=True, blank=True)
    comissao_total_projetada = models.FloatField(null=True, blank=True)
    mensagem = models.TextField(blank=True)

    class Meta:
        ordering = ["-data_processamento", "descricao_pdv"]
        verbose_name = "Histórico OSAB"
        verbose_name_plural = "Históricos OSAB"


class GrossMensal(models.Model):
    parceiro = models.ForeignKey(
        "tickets.Parceiro",
        on_delete=models.CASCADE,
        related_name="gross_mensal",
    )
    anomes = models.IntegerField()
    gross = models.IntegerField(default=0)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["parceiro", "anomes"],
                name="uniq_gross_parceiro_anomes",
            )
        ]
        verbose_name = "Gross mensal"
        verbose_name_plural = "Gross mensal"


class HistoricoChurn(models.Model):
    data_analise = models.DateField(db_index=True)
    parceiro = models.ForeignKey(
        "tickets.Parceiro",
        on_delete=models.CASCADE,
        related_name="historicos_churn",
    )
    pdv_nome = models.CharField(max_length=100)
    anomes_gross = models.IntegerField()
    gross = models.IntegerField()
    churn = models.IntegerField()
    taxa_churn = models.FloatField()
    remanescentes = models.IntegerField()
    bonus_m10 = models.FloatField()
    mensagem = models.TextField(blank=True)

    class Meta:
        ordering = ["pdv_nome", "-anomes_gross"]
        verbose_name = "Histórico de churn"
        verbose_name_plural = "Históricos de churn"


class RelatorioFPD(models.Model):
    lote = models.ForeignKey(
        LoteImportacao,
        on_delete=models.CASCADE,
        related_name="relatorios_fpd",
    )
    parceiro = models.ForeignKey(
        "tickets.Parceiro",
        on_delete=models.CASCADE,
        related_name="relatorios_fpd",
    )
    pdv_nome = models.CharField(max_length=150)
    percentual = models.FloatField()
    total_faturas = models.IntegerField()
    total_abertas = models.IntegerField()
    mensagem = models.TextField(blank=True)
    detalhes = models.JSONField(default=dict, blank=True)
    criado_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-percentual", "pdv_nome"]
        verbose_name = "Relatório FPD"
        verbose_name_plural = "Relatórios FPD"


class RelatorioComissionamento(models.Model):
    lote = models.ForeignKey(
        LoteImportacao,
        on_delete=models.CASCADE,
        related_name="relatorios_comissionamento",
    )
    parceiro = models.ForeignKey(
        "tickets.Parceiro",
        on_delete=models.CASCADE,
        related_name="relatorios_comissionamento",
    )
    pdv_nome = models.CharField(max_length=150)
    qtd_pedido = models.IntegerField(default=0)
    qtd_linha = models.IntegerField(default=0)
    total_pedido = models.FloatField(default=0)
    total_comissao = models.FloatField(default=0)
    mensagem = models.TextField(blank=True)
    arquivo = models.FileField(
        upload_to="gestao/comissionamento/%Y/%m/",
        blank=True,
    )
    detalhes = models.JSONField(default=dict, blank=True)
    criado_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-criado_em", "pdv_nome"]
        verbose_name = "Relatório de comissionamento"
        verbose_name_plural = "Relatórios de comissionamento"

    def __str__(self) -> str:
        return f"{self.pdv_nome} · {self.criado_em:%d/%m %H:%M}"


class RelatorioTarefa(models.Model):
    class TipoRelatorio(models.TextChoices):
        ABERTAS = "abertas", "Tarefas abertas (hoje)"
        FECHADAS = "fechadas", "Tarefas fechadas"
        FUTUROS = "futuros", "Agendamentos futuros"

    lote = models.ForeignKey(
        LoteImportacao,
        on_delete=models.CASCADE,
        related_name="relatorios_tarefa",
    )
    tipo_relatorio = models.CharField(max_length=20, choices=TipoRelatorio.choices, db_index=True)
    parceiro = models.ForeignKey(
        "tickets.Parceiro",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="relatorios_tarefa",
    )
    pdv_nome = models.CharField(max_length=150, blank=True)
    total = models.IntegerField(default=0)
    data_referencia = models.DateField()
    mensagem = models.TextField(blank=True)
    arquivo = models.FileField(upload_to="gestao/tarefas/%Y/%m/", blank=True)
    detalhes = models.JSONField(default=dict, blank=True)
    criado_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-criado_em", "pdv_nome"]
        verbose_name = "Relatório de tarefas"
        verbose_name_plural = "Relatórios de tarefas"

    def __str__(self) -> str:
        return f"{self.get_tipo_relatorio_display()} · {self.pdv_nome or 'MG'}"


class RelatorioVendaIndevida(models.Model):
    lote = models.ForeignKey(
        LoteImportacao,
        on_delete=models.CASCADE,
        related_name="relatorios_vi",
    )
    parceiro = models.ForeignKey(
        "tickets.Parceiro",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="relatorios_vi",
    )
    pdv_nome = models.CharField(max_length=150, blank=True)
    total = models.IntegerField(default=0)
    consolidado = models.BooleanField(default=False)
    data_referencia = models.DateField()
    mensagem = models.TextField(blank=True)
    arquivo = models.FileField(upload_to="gestao/venda_indevida/%Y/%m/", blank=True)
    detalhes = models.JSONField(default=dict, blank=True)
    criado_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-criado_em", "pdv_nome"]
        verbose_name = "Relatório de venda indevida"
        verbose_name_plural = "Relatórios de venda indevida"

    def __str__(self) -> str:
        if self.consolidado:
            return f"VI consolidado · {self.data_referencia}"
        return f"VI · {self.pdv_nome}"


class RelatorioRecompra(models.Model):
    lote = models.ForeignKey(
        LoteImportacao,
        on_delete=models.CASCADE,
        related_name="relatorios_recompra",
    )
    parceiro = models.ForeignKey(
        "tickets.Parceiro",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="relatorios_recompra",
    )
    pdv_nome = models.CharField(max_length=150, blank=True)
    total = models.IntegerField(default=0)
    consolidado = models.BooleanField(default=False)
    data_referencia = models.DateField()
    mensagem = models.TextField(blank=True)
    arquivo = models.FileField(upload_to="gestao/recompra/%Y/%m/", blank=True)
    detalhes = models.JSONField(default=dict, blank=True)
    criado_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-criado_em", "pdv_nome"]
        verbose_name = "Relatório de recompra"
        verbose_name_plural = "Relatórios de recompra"

    def __str__(self) -> str:
        if self.consolidado:
            return f"Recompra consolidado · {self.data_referencia}"
        return f"Recompra · {self.pdv_nome}"


class Destinatario(models.Model):
    class TipoDestino(models.TextChoices):
        INDIVIDUAL = "individual", "Número / contato"
        GRUPO = "grupo", "Grupo WhatsApp"

    parceiro = models.ForeignKey(
        "tickets.Parceiro",
        on_delete=models.CASCADE,
        related_name="destinatarios_gestao",
    )
    nome = models.CharField("Nome do destino", max_length=150)
    jid = models.CharField(
        "JID WhatsApp",
        max_length=80,
        help_text="Número com DDI (ex.: 5531999999999) ou JID de grupo (…@g.us).",
    )
    tipo = models.CharField(
        max_length=20,
        choices=TipoDestino.choices,
        default=TipoDestino.INDIVIDUAL,
    )
    ativo = models.BooleanField(default=True)
    prioridade = models.PositiveIntegerField(default=100)
    envio_osab = models.BooleanField("OSAB", default=True)
    envio_capilaridade = models.BooleanField("Capilaridade", default=True)
    envio_fpd = models.BooleanField("FPD", default=True)
    envio_fpd_critico = models.BooleanField("FPD crítico (global)", default=False)
    envio_churn = models.BooleanField("Churn", default=True)
    envio_comissionamento = models.BooleanField("Comissionamento", default=False)
    envio_tarefas = models.BooleanField("Tarefas", default=False)
    envio_venda_indevida = models.BooleanField("Venda indevida", default=False)
    envio_recompra = models.BooleanField("Recompra", default=False)
    razoes_sociais_comissionamento = models.TextField(
        "Razões sociais (comissionamento)",
        blank=True,
        help_text="Uma por linha (ou separadas por ;). Filtra as abas PEDIDO / LINHA_A_LINHA.",
    )
    criado_em = models.DateTimeField(auto_now_add=True)
    atualizado_em = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["prioridade", "nome"]
        verbose_name = "Destinatário WhatsApp"
        verbose_name_plural = "Destinatários WhatsApp"

    def __str__(self) -> str:
        return f"{self.nome} ({self.parceiro.nome})"


class EnvioWhatsApp(models.Model):
    class Tipo(models.TextChoices):
        CAPILARIDADE = "capilaridade", "Capilaridade"
        OSAB = "osab", "OSAB"
        FPD = "fpd", "FPD"
        FPD_CRITICO = "fpd_critico", "FPD crítico"
        CHURN = "churn", "Churn"
        COMISSIONAMENTO = "comissionamento", "Comissionamento"
        TAREFAS = "tarefas", "Tarefas"
        VENDA_INDEVIDA = "venda_indevida", "Venda indevida"
        RECOMPRA = "recompra", "Recompra"
        RESUMO = "resumo", "Resumo geral"
        TESTE = "teste", "Teste SyncWA"

    class Status(models.TextChoices):
        PENDENTE = "pendente", "Pendente"
        ENVIADO = "enviado", "Enviado (fila SyncWA)"
        ERRO = "erro", "Erro"
        IGNORADO = "ignorado", "Ignorado"

    tipo = models.CharField(max_length=30, choices=Tipo.choices, db_index=True)
    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.PENDENTE, db_index=True
    )
    parceiro = models.ForeignKey(
        "tickets.Parceiro",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="envios_whatsapp",
    )
    destinatario = models.ForeignKey(
        Destinatario,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="envios",
    )
    destino_jid = models.CharField(max_length=80)
    destino_nome = models.CharField(max_length=150, blank=True)
    mensagem = models.TextField()
    modo_teste = models.BooleanField(default=False)
    syncwa_message_id = models.CharField(max_length=80, blank=True)
    syncwa_status = models.CharField(max_length=40, blank=True)
    erro = models.TextField(blank=True)
    criado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="envios_gestao",
    )
    criado_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-criado_em"]
        verbose_name = "Envio WhatsApp"
        verbose_name_plural = "Envios WhatsApp"

    def __str__(self) -> str:
        return f"{self.get_tipo_display()} → {self.destino_nome or self.destino_jid}"
