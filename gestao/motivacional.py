from __future__ import annotations

import re
from datetime import date, datetime, timedelta
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from tickets.models import Parceiro

# Catálogo comercial (120 frases inéditas) — foco direto em campo/PAP,
# capilaridade ativa, conversão, abordagem, agendamento e fechamento de metas.
FRASES_MOTIVACIONAIS_VENDAS: list[str] = [
    "Capilaridade forte é vendedor posicionado cedo e pedido entrando desde a primeira hora.",
    "No PAP, quem bate na primeira porta às 8h já sai na frente de quem espera o movimento aparecer.",
    "Vendedor ativo é vendedor com pelo menos um pedido no sistema. Bora zerar a fila de improdutivos hoje!",
    "Meta diária não se acumula para amanhã: cada turno precisa fechar a sua conta.",
    "Abordagem rápida, argumento direto na dor do cliente e pedido fechado na hora: esse é o jogo de hoje.",
    "Capilaridade não é só ter TT cadastrada, é transformar cada TT da equipe em venda instalada.",
    "Rua trabalhada com método não falha: mapeie a quadra, fale com o decisor e garanta o agendamento.",
    "O melhor termômetro da operação é a produtiva do dia: cada vendedor colocando número na tela.",
    "Não passe por uma fachada com viabilidade sem oferecer. O cliente que você pula hoje compra do concorrente amanhã.",
    "Volume de abordagem gera volume de proposta; volume de proposta gera meta batida.",
    "Time comercial afiado não aceita o 'vou pensar' sem antes mostrar a vantagem de fechar agora.",
    "Produtividade na veia: se metade do time já pontuou, é hora de puxar a outra metade para o jogo!",
    "Venda boa é venda com cadastro limpo, agendamento confirmado e cliente acompanhado até instalar.",
    "Cada TT ativa no campo representa faturamento na mesa. Ninguém fica no zero hoje!",
    "No porta a porta, o ritmo da manhã define a tranquilidade do fechamento da tarde.",
    "Mais rua, mais contato olho no olho e menos tempo parado: resultado comercial responde à intensidade.",
    "Cliente indeciso fecha com quem transmite domínio da oferta e rapidez no cadastro.",
    "Bater meta todos os dias é questão de rotina: primeira visita cedo, acompanhamento de esteira e fechamento forte.",
    "Onde tem CDO com porta livre, tem oportunidade de venda esperando abordagem.",
    "Time que acompanha a parcial turno a turno corrige a rota a tempo e não perde o dia.",
    "A diferença entre um dia mediano e um recorde de vendas está nas abordagens extras antes do fim do turno.",
    "Quem domina a viabilidade da própria praça não perde viagem: vai direto onde instala rápido.",
    "Zero improdutivo na equipe: quando todo vendedor faz a sua parte, o PDV dispara no ranking.",
    "Oferta na ponta da língua e cadastro ágil no app: tire o atrito da venda e feche no ato.",
    "Não espere o cliente procurar internet; leve a solução até a porta dele com energia comercial.",
    "Todo 'não' na rua só aproxima o vendedor do próximo 'sim' — desde que ele não diminua o passo.",
    "Foco total em conversão: visita feita precisa virar proposta, e proposta precisa virar pedido.",
    "Meta de capilaridade se resolve no campo: equipe espalhada, praça coberta e venda subindo.",
    "O segredo do PAP campeão é simples: constância de abordagem do primeiro ao último minuto em campo.",
    "Revise os clientes que pediram retorno na semana passada: ali já tem venda pronta esperando o seu contato.",
    "Venda cadastrada cedo já entra na fila de agendamento mais rápido. Ganhe velocidade logo pela manhã!",
    "Quando cada vendedor assume o compromisso de não fechar o dia zerado, a meta do PDV vira consequência.",
    "Argumento comercial forte é aquele que compara velocidade, estabilidade e custo-benefício sem rodeios.",
    "Trabalhe cada rua até o fim: muitas vezes a melhor venda do dia está na última casa da quadra.",
    "Equipe de alta performance mede o dia por pedidos gerados, não apenas por horas na rua.",
    "Transforme consulta de viabilidade em contrato fechado: velocidade de resposta ganha o cliente.",
    "Se o primeiro turno foi abaixo do plano, o segundo turno é a hora de dobrar o volume de abordagens.",
    "Bons vendedores aproveitam o movimento; vendedores de ponta criam o próprio movimento na praça.",
    "Peça indicação a cada cliente atendido: quem acabou de comprar sempre conhece um vizinho precisando de fibra.",
    "Não deixe TT parada no relatório: vendedor escalado é vendedor produzindo e pontuando.",
    "Qualidade na venda começa na abordagem certa: titular correto, meio de pagamento alinhado e agenda firme.",
    "O ranking do mês é construído no detalhe de cada dia útil. Faça o resultado de hoje valer!",
    "Liderar a praça exige presença: camisa no corpo, rota definida e meta clara para cada vendedor.",
    "Cada conversa no balcão ou no portão é uma chance real de colocar mais uma venda na conta.",
    "Mais execução e menos improviso: saiba exatamente quantos pedidos faltam para o plano de hoje e busque um por um.",
    "A rua recompensa quem insiste: se uma quadra está devagar, mude a abordagem ou avance para a próxima célula.",
    "Fechamento comercial se faz com pergunta direta: 'Qual o melhor período para instalarmos a sua fibra amanhã?'",
    "Equipe alinhada logo cedo não perde tempo: cada um na sua rota e olho no resultado da carteira.",
    "O cliente compra confiança antes de comprar megas. Mostre segurança e feche o pedido na hora!",
    "Produtividade diária é inegociável: cada vendedor ativo tem potencial para colocar venda hoje.",
    "Aproveite os horários de pico na rua para abordar quem está chegando ou saindo de casa.",
    "Não trate a meta do dia como teto, trate como piso: bateu o plano, acelere para abrir gordura no mês!",
    "Vendedor que conhece os planos de cor não gagueja na objeção e converte o dobro.",
    "Olhe para o relatório de capilaridade com mentalidade de dono: quem ainda não vendeu precisa entrar no jogo agora.",
    "Cada pedido aprovado hoje é instalação na esteira amanhã e comissão garantida no fechamento.",
    "Mantenha o funil cheio: enquanto uma venda está subindo no sistema, já engate a próxima abordagem.",
    "Comércio local, residências e pequenos negócios: toda porta na área de cobertura é um cliente em potencial.",
    "Não aceite fechar o turno sem testar uma abordagem nova nos clientes indecisos.",
    "A força do PDV vem da distribuição da venda: quando toda a equipe pontua, o volume multiplica.",
    "Check-in na rota, foco nas células com viabilidade aberta e conversão máxima em cada abordagem!",
    "Quem controla o número de abordagens por hora nunca fica refém da sorte no fim do dia.",
    "Use os casos de clientes já instalados na mesma rua como prova social para convencer o vizinho.",
    "Disciplina comercial é fazer no dia difícil exatamente o mesmo volume de contatos do dia fácil.",
    "Meta quebrada por vendedor fica leve para todos: 1 a 2 vendas por TT mudam o patamar do parceiro.",
    "Evite retrabalho na esteira: confira documento, endereço e telefone com atenção antes de concluir o pedido.",
    "O horário comercial passa rápido: priorize falar com clientes e deixe tarefas burocráticas para depois do pico.",
    "Sondagem rápida descobre o que o cliente valoriza: preço, velocidade no Wi-Fi ou instalação imediata.",
    "Não subestime o cliente que diz estar satisfeito com a operadora atual — mostre a oferta e gere a comparação!",
    "Time que comemora cada pedido no grupo contagia quem ainda está buscando a primeira venda do dia.",
    "Foco nos condomínios e ruas de alta densidade: onde há concentração de moradores, o giro de abordagem é maior.",
    "Se o cliente achou caro, mostre o custo por dia e o ganho de estabilidade para toda a família.",
    "A melhor hora para puxar a próxima venda é imediatamente após acabar de fechar uma: aproveite o embalo!",
    "Vendedor preparado anda com argumentos para Varejo e PME: cada CNPJ na rota vale ouro.",
    "Capilaridade 100% produtiva é o alvo: acompanhe de perto quem está na rua e destrave as dúvidas na hora.",
    "Não deixe lead esfriar no WhatsApp: resposta em menos de 5 minutos aumenta drasticamente a conversão.",
    "Planejamento de rota evita caminhada perdida: concentre a equipe onde a rede está pronta para instalar.",
    "Todo dia útil pesa no atingimento do mês. Entre em campo hoje para ganhar o jogo!",
    "Superação comercial não é discurso, é colocar mais 10 abordagens na rua quando todo mundo já parou.",
    "Venda consultiva no PAP: descubra quantas pessoas usam a internet na casa e encaixe a velocidade certa.",
    "Acompanhe suas vendas abertas: pedido agendado e instalado rápido mantém a carteira saudável.",
    "Quando o supervisor e o vendedor falam a língua dos números, o plano diário deixa de ser desafio e vira rotina.",
    "Abordagem com postura profissional, crachá visível e sorriso aberto abre portas em qualquer bairro.",
    "Não guarde ficha para subir depois: subiu na hora, garantiu o slot de agenda para o cliente.",
    "Use a parcial do dia como combustível: veja quem já destravou e puxe o restante da equipe junto!",
    "Cada ponto percentual a mais na capilaridade representa mais vendedores sustentando o resultado do PDV.",
    "Feche a manhã com pelo menos metade da meta do dia encaminhada para trabalhar a tarde no ataque.",
    "Objeção de fidelidade ou preço se vence na ponta do lápis: mostre o benefício real ao cliente.",
    "O campo é soberano: quem está na rua abordando sempre encontra negócio onde ninguém mais viu.",
    "Mantenha o foco no que gera caixa: TT ativa, proposta apresentada, contrato assinado e OS agendada.",
    "Nenhum vendedor entra em campo para empatar: a meta de hoje existe para ser superada!",
    "Giro rápido no PAP: se a casa está vazia, anote o número para repasse no fim da tarde e siga para a próxima.",
    "Reativar um vendedor zerado no mês vale tanto quanto abrir uma praça nova. Dê suporte e coloque-o para vender!",
    "Clareza na oferta evita cancelamento: explique o plano, confirme o pagamento e garanta um cliente fiel.",
    "A consistência da carteira se mede pela base ativa vendendo todos os dias, sem depender de um único vendedor.",
    "Bora transformar presença de rua em pedido no sistema: foco, ritmo forte e fechamento direto!",
    "Em vendas, velocidade é vantagem competitiva: quem aborda primeiro e responde rápido leva o contrato.",
    "Olho no plano do dia e pé no acelerador: cada venda conta para manter o PDV no topo da regional!",
    "Aproveite cada conversa para deixar seu contato e pedir referências na vizinhança: crie sua rede na praça.",
    "Não existe praça saturada para quem faz abordagem bem feita e conhece os diferenciais do produto.",
    "Reduza o intervalo entre uma abordagem e outra: manter o ritmo aquecido deixa o discurso mais afiado.",
    "Vendedor que bate meta cedo continua na pegada para construir o próprio comissionamento recorde.",
    "Faça o básico bem feito todos os dias: horário cumprido, abordagem energética e acompanhamento de carteira.",
    "Onde há comércio aberto na rota, há oportunidade de venda empresarial. Aborde o lojista com confiança!",
    "O resultado do mês não cai do céu na última semana: ele é construído no acumulado de cada parcial.",
    "Cheque a lista da equipe abaixo, identifique quem precisa de apoio hoje e coloque todo o time para pontuar!",
    "Atitude de fechador: conduza a conversa para o cadastro assim que o cliente demonstrar interesse.",
    "Um time com capilaridade alta não sente oscilação de mercado: sempre tem gente vendendo e puxando o número.",
    "Transforme o relatório de hoje em plano de ação imediato: cada TT ativa é uma alavanca de crescimento.",
    "Energia comercial lá no alto, argumento afiado e foco total na conversão. Vamos buscar o resultado de hoje!",
    "Falar com 30 clientes no dia garante estatisticamente o fechamento: confie no volume de trabalho!",
    "Quem acompanha seus indicadores sabe exatamente onde apertar o passo. Olho na capilaridade e foco na rua!",
    "Não deixe para as 18h o pedido que pode ser fechado antes do almoço. Acelere o ritmo agora!",
    "Venda forte começa na mentalidade da equipe: hoje é dia de todos os vendedores saírem do zero.",
    "Cobertura de praça + agilidade no sistema = meta batida. Bora executar com excelência!",
    "Cada cliente conquistado na rua fortalece o nome do parceiro na cidade. Faça um atendimento impecável!",
    "Foco na produtiva diária: puxar quem ainda está sem venda é o caminho mais curto para dobrar o resultado.",
    "Ritmo comercial intenso do início ao fim do expediente: cada porta batida conta para o fechamento!",
    "Organize os contatos de repescagem do mês e combine com a ação de rua: ataque nas duas frentes hoje!",
    "Meta na mão, equipe posicionada e foco na execução: vamos fazer deste turno o mais produtivo da semana!",
    "Resultado forte se faz com time completo pontuando. Confira os números abaixo e vamos pra cima!",
]

# Chamadas de fechamento variadas para não repetir sempre o mesmo rodapé na mensagem.
CHAMADAS_FECHAMENTO_CAPILARIDADE: list[str] = [
    (
        "Foco em colocar todo o time para pontuar e acelerar as vendas de hoje! 💪📈\n"
        "Confira abaixo o panorama de capilaridade da equipe: 👇"
    ),
    (
        "Bora puxar a produtiva da equipe e transformar presença de campo em pedido no sistema! 🚀🔥\n"
        "Segue o posicionamento atualizado de capilaridade: 👇"
    ),
    (
        "Olho nos números do time: cada vendedor ativo pontuando faz a meta do dia acontecer! 🎯💼\n"
        "Acompanhe abaixo o relatório de capilaridade: 👇"
    ),
    (
        "Hora de acionar quem ainda está zerado e manter o ritmo forte na rua! ⚡🏃‍♂️\n"
        "Veja abaixo o status detalhado da capilaridade do PDV: 👇"
    ),
    (
        "Meta no radar e execução em campo: vamos zerar os improdutivos hoje! 🔥📊\n"
        "Segue abaixo a fotografia atualizada da capilaridade: 👇"
    ),
    (
        "Time completo produzindo é o caminho mais rápido para o topo do ranking! 🏆💪\n"
        "Confira os dados de capilaridade da equipe logo abaixo: 👇"
    ),
    (
        "Vamos converter cada abordagem em contrato fechado neste turno! 🚀✅\n"
        "Segue o acompanhamento de capilaridade do time: 👇"
    ),
    (
        "Acompanhe quem já destravou no mês e apoie quem precisa colocar a primeira venda! 🤝📈\n"
        "Veja abaixo o relatório completo de capilaridade: 👇"
    ),
    (
        "Ritmo comercial forte na praça e foco total em conversão hoje! 💥🎯\n"
        "Confira abaixo como está a capilaridade da sua operação: 👇"
    ),
    (
        "Cada TT ativa vendendo puxa o atingimento da carteira para cima! 📊🔥\n"
        "Segue abaixo o detalhamento de capilaridade da equipe: 👇"
    ),
    (
        "Bora transformar rota na rua em pedido agendado no sistema! 🚀💪\n"
        "Acompanhe abaixo o consolidado de capilaridade do PDV: 👇"
    ),
    (
        "Disciplina na execução e acompanhamento de perto em cada vendedor! 🎯⚡\n"
        "Confira abaixo a atualização da capilaridade: 👇"
    ),
]

_REGEX_FRASE_ITALICO = re.compile(r"\n\n_(.+?)_\n\n", re.DOTALL)


def _indice_rotacionado(ordinal: int, total: int, passo: int = 37) -> int:
    """Permuta a ordem pelo calendário usando passo coprimo para evitar sequência previsível."""
    if total <= 1:
        return 0
    return (ordinal * passo) % total


def _frases_ja_enviadas(parceiro: Parceiro | None = None, dias: int = 120) -> set[str]:
    """Busca no histórico de EnvioWhatsApp as frases motivacionais já enviadas recentemente."""
    try:
        from django.utils import timezone

        from .models import EnvioWhatsApp

        limite = timezone.now() - timedelta(days=dias)
        qs = EnvioWhatsApp.objects.filter(
            tipo=EnvioWhatsApp.Tipo.CAPILARIDADE,
            criado_em__gte=limite,
        )
        if parceiro is not None and getattr(parceiro, "pk", None):
            qs_pdv = qs.filter(parceiro_id=parceiro.pk)
            if qs_pdv.exists():
                qs = qs_pdv
        mensagens = list(qs.order_by("-criado_em").values_list("mensagem", flat=True)[:250])
        usadas: set[str] = set()
        for msg in mensagens:
            if not msg:
                continue
            m = _REGEX_FRASE_ITALICO.search(str(msg))
            if m:
                usadas.add(m.group(1).strip())
        return usadas
    except Exception:
        return set()


def obter_frase_do_dia(
    data: date | None = None,
    *,
    parceiro: Parceiro | None = None,
    evitar_historico: bool | None = None,
) -> str:
    """Retorna a frase comercial do dia, pulando frases já enviadas no histórico quando aplicável."""
    usar_historico = evitar_historico if evitar_historico is not None else (data is None or parceiro is not None)
    if data is None:
        data = date.today()
    total = len(FRASES_MOTIVACIONAIS_VENDAS)
    base_idx = _indice_rotacionado(data.toordinal(), total, passo=37)

    if not usar_historico:
        return FRASES_MOTIVACIONAIS_VENDAS[base_idx]

    usadas = _frases_ja_enviadas(parceiro=parceiro)
    if not usadas:
        return FRASES_MOTIVACIONAIS_VENDAS[base_idx]

    for offset in range(total):
        candidata = FRASES_MOTIVACIONAIS_VENDAS[(base_idx + offset) % total]
        if candidata not in usadas:
            return candidata
    return FRASES_MOTIVACIONAIS_VENDAS[base_idx]


def obter_chamada_capilaridade(data: date | None = None, *, parceiro: Parceiro | None = None) -> str:
    """Retorna o texto de fechamento variado para a mensagem de capilaridade."""
    if data is None:
        data = date.today()
    total = len(CHAMADAS_FECHAMENTO_CAPILARIDADE)
    salto_pdv = (int(parceiro.pk) if (parceiro and getattr(parceiro, "pk", None)) else 0)
    idx = (data.toordinal() * 7 + salto_pdv) % total
    return CHAMADAS_FECHAMENTO_CAPILARIDADE[idx]


def montar_mensagem_motivacional_pdv(
    parceiro: Parceiro,
    data: date | None = None,
    agora: datetime | None = None,
) -> str:
    """Monta a saudação (bom dia/boa tarde/boa noite) comercial do PDV sem repetir histórico."""
    from django.utils import timezone

    from .pipelines.resultados import saudacao_horario

    agora = agora or timezone.localtime()
    data_ref = data or agora.date()
    emoji, saudacao = saudacao_horario(agora.hour)
    evitar_hist = data is None
    frase = obter_frase_do_dia(
        data_ref,
        parceiro=parceiro,
        evitar_historico=evitar_hist,
    )
    chamada = obter_chamada_capilaridade(data_ref, parceiro=parceiro)
    nome_pdv = (parceiro.nome or "Parceiro").strip()
    return (
        f"{emoji} *{saudacao}, time {nome_pdv}!* 🚀\n\n"
        f"_{frase}_\n\n"
        f"{chamada}"
    )
