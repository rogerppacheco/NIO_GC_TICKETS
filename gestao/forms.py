from __future__ import annotations

import re

from django import forms

from tickets.models import Parceiro

from .models import Destinatario
from .pipelines.parcial_vendas import HORARIOS_PARCIAL, ROTULOS_TURNO


class DestinatarioForm(forms.ModelForm):
    class Meta:
        model = Destinatario
        fields = (
            "parceiro",
            "nome",
            "jid",
            "tipo",
            "ativo",
            "prioridade",
            "envio_osab",
            "envio_capilaridade",
            "envio_fpd",
            "envio_fpd_critico",
            "envio_churn",
            "envio_comissionamento",
            "envio_tarefas",
            "envio_venda_indevida",
            "envio_recompra",
            "envio_resultados",
            "ranking_consolidado",
            "email",
            "email_osab",
            "email_capilaridade",
            "email_fpd",
            "email_fpd_critico",
            "email_churn",
            "email_comissionamento",
            "email_tarefas",
            "email_venda_indevida",
            "email_recompra",
            "email_resultados",
            "razoes_sociais_comissionamento",
        )
        widgets = {
            "nome": forms.TextInput(attrs={"placeholder": "Ex.: Grupo Inova / João"}),
            "jid": forms.TextInput(
                attrs={"placeholder": "5531999999999 ou 120363...@g.us", "class": "mono"}
            ),
            "prioridade": forms.NumberInput(attrs={"min": 1}),
            "razoes_sociais_comissionamento": forms.Textarea(
                attrs={
                    "rows": 3,
                    "placeholder": "Uma razão social por linha (ou ;)\nEx.: LUISA SERVICOS DE TELEFONIA...",
                }
            ),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["parceiro"].label_from_instance = self._rotulo_parceiro

    @staticmethod
    def _rotulo_parceiro(obj: Parceiro) -> str:
        spec = getattr(obj, "especialista", None)
        if not spec:
            return f"{obj.nome} · sem GC"
        nome = spec.get_full_name() or spec.username
        gerencia = (getattr(getattr(spec, "perfil_staff", None), "gerencia", "") or "").strip()
        if gerencia:
            return f"{obj.nome} · {nome} · {gerencia}"
        return f"{obj.nome} · {nome}"

    def clean(self):
        cleaned = super().clean()
        consolidado = cleaned.get("ranking_consolidado")
        parceiro = cleaned.get("parceiro")
        if consolidado:
            if cleaned.get("tipo") != Destinatario.TipoDestino.GRUPO:
                self.add_error("tipo", "Ranking consolidado exige tipo Grupo WhatsApp.")
            cleaned["envio_resultados"] = True
        elif not parceiro:
            self.add_error("parceiro", "Informe o PDV ou marque Ranking consolidado.")
        return cleaned

    def clean_jid(self):
        jid = (self.cleaned_data.get("jid") or "").strip()
        if not jid:
            raise forms.ValidationError("Informe o número ou o JID do grupo.")
        if "@" in jid:
            return jid
        digitos = re.sub(r"\D", "", jid)
        if not digitos:
            raise forms.ValidationError(
                "JID inválido. Use o número com DDI (ex.: 5531999999999) "
                "ou o JID do grupo (…@g.us) — não o nome do contato."
            )
        return jid


class UploadBaseForm(forms.Form):
    arquivo = forms.FileField(label="Arquivo")

    def __init__(self, *args, extensoes=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.extensoes = extensoes or [".xlsx", ".xlsb", ".xls"]
        self.fields["arquivo"].help_text = "Formatos: " + ", ".join(self.extensoes)

    def clean_arquivo(self):
        arquivo = self.cleaned_data["arquivo"]
        nome = (arquivo.name or "").lower()
        if not any(nome.endswith(ext) for ext in self.extensoes):
            raise forms.ValidationError("Formato inválido. Use " + ", ".join(self.extensoes))
        return arquivo


class PeriodoForm(forms.Form):
    ano = forms.IntegerField(min_value=2020, max_value=2100, label="Ano")
    mes = forms.IntegerField(min_value=1, max_value=12, label="Mês")


class GrossForm(forms.Form):
    parceiro = forms.ModelChoiceField(queryset=Parceiro.objects.filter(ativo=True), label="Parceiro")
    anomes = forms.IntegerField(
        min_value=202001,
        max_value=210012,
        label="Safra (AAAAMM)",
        help_text="Ex.: 202507",
    )
    gross = forms.IntegerField(min_value=0, label="Gross")


class ParcialResultadoForm(forms.Form):
    arquivo = forms.FileField(
        label="Base Excel",
        required=False,
        help_text=(
            "Exporte da dashboard: colunas PDV, vendas totais do mês e referência D-7 "
            "(TOTAL / REALIZADO e D-7 ou VENDAS_D7). .xlsx, .xls ou .xlsb."
        ),
    )
    turno = forms.ChoiceField(
        label="Horário do parcial",
        choices=[(str(h), f"{ROTULOS_TURNO[h]} — parcial do turno") for h in HORARIOS_PARCIAL],
        required=False,
        help_text="12h, 15h ou 18h. Se vazio, usa o turno atual.",
    )
    caption = forms.CharField(
        label="Legenda complementar",
        required=False,
        max_length=1024,
        widget=forms.Textarea(
            attrs={
                "rows": 6,
                "placeholder": "Opcional — a legenda principal é gerada automaticamente.",
            }
        ),
        help_text="Saudação, frase do dia e dados do parcial. *time* vira o nome do PDV nos envios individuais.",
    )
    parceiro = forms.ModelChoiceField(
        queryset=Parceiro.objects.none(),
        required=False,
        label="PDV (envio avulso)",
    )
    destinatario = forms.ModelChoiceField(
        queryset=Destinatario.objects.none(),
        required=False,
        label="Grupo gerência / parceiros",
    )

    def __init__(self, *args, parceiros=None, grupos=None, **kwargs):
        super().__init__(*args, **kwargs)
        qs = parceiros if parceiros is not None else Parceiro.objects.filter(ativo=True)
        self.fields["parceiro"].queryset = qs
        self.fields["destinatario"].queryset = grupos or Destinatario.objects.none()

    def clean_arquivo(self):
        arquivo = self.cleaned_data.get("arquivo")
        if not arquivo:
            return arquivo
        nome = (arquivo.name or "").lower()
        if not nome.endswith((".xlsx", ".xls", ".xlsb")):
            raise forms.ValidationError("Use a base em Excel (.xlsx, .xls ou .xlsb).")
        if arquivo.size and arquivo.size > 12 * 1024 * 1024:
            raise forms.ValidationError("A planilha deve ter no máximo 12 MB.")
        return arquivo

    def turno_int(self) -> int | None:
        raw = self.cleaned_data.get("turno")
        if not raw:
            return None
        try:
            return int(raw)
        except (TypeError, ValueError):
            return None


class PracaBTUForm(forms.Form):
    nome = forms.CharField(
        label="Município / praça BTU",
        max_length=120,
        widget=forms.TextInput(attrs={"placeholder": "Ex.: Ipatinga"}),
    )


class GdpImportForm(forms.Form):
    arquivo_b2c = forms.FileField(
        label="GDP B2C",
        required=False,
        help_text="Planilha 20xx_B2C_GDP.xlsx. Aba PAP (Local), portfólio vigente NOVO ESPECIAL.",
    )
    arquivo_b2b = forms.FileField(
        label="GDP B2B",
        required=False,
        help_text="Opcional. Se B2C e B2B divergirem, a união das praças ESPECIAL entra no ranking.",
    )

    def _validar_xlsx(self, arquivo):
        if not arquivo:
            return arquivo
        nome = (arquivo.name or "").lower()
        if not nome.endswith((".xlsx", ".xls", ".xlsb")):
            raise forms.ValidationError("Use o GDP em .xlsx.")
        return arquivo

    def clean_arquivo_b2c(self):
        return self._validar_xlsx(self.cleaned_data.get("arquivo_b2c"))

    def clean_arquivo_b2b(self):
        return self._validar_xlsx(self.cleaned_data.get("arquivo_b2b"))

    def clean(self):
        dados = super().clean()
        if not dados.get("arquivo_b2c") and not dados.get("arquivo_b2b"):
            raise forms.ValidationError("Envie o GDP B2C e/ou o GDP B2B.")
        return dados
