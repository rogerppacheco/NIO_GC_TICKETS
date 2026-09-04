from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from tickets.models import Parceiro

# Catálogo amplo de frases motivacionais focadas em vendas, atitude comercial,
# superação, consistência e fechamento de metas.
FRASES_MOTIVACIONAIS_VENDAS: list[str] = [
    "O sucesso em vendas é a soma de pequenos esforços repetidos dia após dia com entusiasmo e consistência.",
    "Cada novo dia traz uma folha em branco para bater recordes. Acredite no seu produto, atenda com o coração e vá para o fechamento!",
    "Vender não é empurrar produtos, é conectar soluções aos sonhos e necessidades das pessoas. Faça a diferença hoje!",
    "O 'não' você já tem, o 'sim' está esperando a sua energia, o seu sorriso e a sua persistência!",
    "A meta de vendas do mês se conquista hora a hora, cliente a cliente. Foco na execução e pés no chão!",
    "Entusiasmo é a faísca que acende a decisão de compra. Coloque paixão em cada atendimento!",
    "Grandes vendedores não esperam o cliente ideal: eles transformam cada oportunidade em um grande negócio.",
    "A disciplina é a ponte invisível que transforma a meta de vendas em celebração no fim do mês.",
    "Quem tem atitude positiva encontra soluções onde os outros veem obstáculos. Bora ser protagonista hoje!",
    "Cada objeção do cliente é apenas um pedido de mais segurança. Transmita confiança e feche a venda!",
    "Mais vale um passo firme em direção à meta hoje do que grandes planos adiados para amanhã. A hora de vender é agora!",
    "A sua melhor venda sempre começa com uma escuta atenta e uma vontade genuína de ajudar.",
    "Vendedores comuns falam de produtos. Vendedores de elite contam histórias e transformam realidades.",
    "O melhor fechamento de vendas acontece quando você cuida de cada detalhe do atendimento com excelência.",
    "Celebre cada contrato assinado, aprenda com cada recusa e nunca perca a fome de crescer!",
    "A consistência vence o talento em todos os dias em que o talento não tem consistência. Mantenha o ritmo!",
    "Hoje é dia de buscar aquele cliente que estava em dúvida e mostrar por que a NIO é a melhor escolha!",
    "Coragem não é a ausência do medo de ouvir um 'não', é a certeza de que a sua meta é maior do que qualquer recusa.",
    "Venda com clareza, encante com dedicação e fidelize com verdade. O resultado vem como consequência!",
    "A persistência abre portas que a sorte nem sequer conhece. Vá além no dia de hoje!",
    "Vender é uma arte diária de superação. Olhe para a meta, respire fundo e faça acontecer!",
    "A energia que você coloca na primeira ligação ou na primeira abordagem dita o ritmo de todo o seu dia. Comece com 100%!",
    "Metas ousadas exigem atitudes fora do comum. Dê o seu melhor em cada contato comercial hoje!",
    "Um vendedor campeão não se abala com o início do dia: ele constrói o resultado a cada minuto trabalhado.",
    "O maior concorrente do seu sucesso hoje é a procrastinação. Foco no cliente, telefone na mão e bora vender!",
    "Sorriso na voz e brilho nos olhos: essa é a assinatura dos que nasceram para liderar em vendas!",
    "Não deixe para o final do mês o esforço que pode garantir a sua meta logo no início. Cada dia conta!",
    "Quando você acredita 100% no valor que entrega, vender se torna natural e irresistível.",
    "Dificuldades preparam pessoas comuns para resultados extraordinários. Acredite no seu potencial hoje!",
    "A excelência em vendas não é um ato isolado, é um hábito diário. Continue acelerando!",
    "O cliente percebe quando você está presente por inteiro. Entregue atenção total e colha grandes vendas!",
    "A diferença entre sonhar com a meta e bater a meta é a quantidade de ação que você coloca no seu dia.",
    "O segredo para vender mais é simples: fale com mais pessoas, ouça com mais carinho e proponha soluções com convicção.",
    "Hoje é o melhor dia da semana para surpreender a todos e bater o seu próprio recorde pessoal!",
    "Grandes conquistas são feitas de decisões rápidas e muita atitude. Faça o seu dia ser inesquecível!",
    "O mercado premia quem tem velocidade de atendimento e calor humano. Seja a referência do seu cliente!",
    "Mantenha a mente afiada, a postura confiante e a meta no radar. O topo é o nosso lugar!",
    "Quem planta visitas, contatos e empatia colhe vendas, respeito e comissões no final do mês.",
    "Não espere as condições perfeitas para acelerar. Faça o melhor com a energia que você tem agora!",
    "A maior força de uma equipe de vendas é o espírito coletivo de vitória. Juntos vamos muito mais longe!",
    "Vender é levar liberdade e conexão para as pessoas. Tenha orgulho do que você faz todos os dias!",
    "Para quem tem vontade de vencer, cada objeção se torna um trampolim para o fechamento!",
    "O segredo da alta performance em vendas é acordar decidido a ser 1% melhor do que ontem.",
    "Foque nas coisas que você controla: o seu preparo, a sua dedicação e a quantidade de contatos. O resultado virá!",
    "O sucesso não bate na porta: ele é conquistado por quem vai para a rua, liga e busca com determinação.",
    "Transforme a sua energia em contratos e a sua dedicação em resultados. Hoje é dia de show de vendas!",
    "Nunca subestime o poder de uma última tentativa no final da tarde. Muitas metas são batidas na prorrogação!",
    "Com disciplina, energia e método, nenhuma meta é inalcançável. Vamos pra cima!",
    "Trate cada lead como o negócio mais importante da semana. O respeito e o entusiasmo fecham portas e abrem contratos!",
    "O campeão não é aquele que nunca erra, é aquele que nunca desiste de vender e aprender!",
    "Hoje é dia de acelerar, prospectar e converter. Time campeão joga para ganhar!",
]


def obter_frase_do_dia(data: date | None = None) -> str:
    """Retorna uma frase motivacional com base na data do calendário.

    Usa a data ordinal (dias contínuos desde o início da era cristã)
    para garantir rotação contínua dia após dia, sem repetições consecutivas.
    """
    if data is None:
        data = date.today()
    indice = data.toordinal() % len(FRASES_MOTIVACIONAIS_VENDAS)
    return FRASES_MOTIVACIONAIS_VENDAS[indice]


def montar_mensagem_motivacional_pdv(parceiro: Parceiro, data: date | None = None) -> str:
    """Monta a mensagem de Bom Dia motivacional personalizada para o PDV."""
    frase = obter_frase_do_dia(data)
    nome_pdv = (parceiro.nome or "Parceiro").strip()
    return (
        f"☀️ *Bom dia, time {nome_pdv}!* 🚀\n\n"
        f"_{frase}_\n\n"
        f"Bora pra cima que hoje é dia de bater metas e acelerar os resultados! 💪🔥\n"
        f"Segue abaixo o relatório de capilaridade da equipe: 👇"
    )
