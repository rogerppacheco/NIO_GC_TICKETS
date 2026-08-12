from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import SimpleTestCase
from django.utils.datastructures import MultiValueDict

from .forms import MultipleFileField, TicketCreateForm
from .models import TipoDemanda


class MultipleFileFieldTests(SimpleTestCase):
    def test_aceita_lista_de_arquivos(self):
        campo = MultipleFileField(required=False)
        arquivo = SimpleUploadedFile("evidencia.jpeg", b"fake-image", content_type="image/jpeg")
        limpo = campo.clean([arquivo])
        self.assertEqual(len(limpo), 1)
        self.assertEqual(limpo[0].name, "evidencia.jpeg")

    def test_lista_vazia_quando_opcional(self):
        campo = MultipleFileField(required=False)
        self.assertEqual(campo.clean([]), [])


class TicketCreateEvidenciasTests(SimpleTestCase):
    def test_abrir_chamado_ti_aceita_anexo_via_getlist(self):
        """request.FILES.getlist devolve lista; FileField padrão acusava encoding."""
        arquivo = SimpleUploadedFile("10843955.jpeg", b"conteudo", content_type="image/jpeg")
        files = MultiValueDict({"evidencias": [arquivo]})
        form = TicketCreateForm(
            data={
                "tipo": TipoDemanda.ABRIR_CHAMADO_TI,
                "pedido": "10843955",
                "documento_cliente": "37161261600",
                "solicitante_nome": "WALTER",
                "tt_vendedor": "TT832209",
                "tt_backoffice": "TT832207",
                "observacoes": "AGENDAMENTO REALIZADO NAO ATRIBUI",
                "descricao": "PEDIDO NAO GEROU ATRIBUICAO",
            },
            files=files,
        )
        form.is_valid()
        self.assertNotIn("evidencias", form.errors)
        erros = " ".join(str(e) for e in form.errors.get("evidencias", []))
        self.assertNotIn("codificação", erros)
        self.assertEqual(len(form.cleaned_data.get("evidencias") or []), 1)
