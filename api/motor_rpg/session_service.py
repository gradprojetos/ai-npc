import logging
from db.session import SessionLocal
from db.models import Usuario, SessaoJogo, HistoricoMensagens, EstadoSessao

logger = logging.getLogger(__name__)


def reset_player_session(telegram_id: int) -> bool:
    """Apaga o histórico de mensagens e reseta as variáveis do jogo para o jogador."""
    logger.info(f"Resetando sessão de jogo para telegram_id={telegram_id}")
    with SessionLocal() as db:
        usuario = db.query(Usuario).filter(Usuario.telegram_id == telegram_id).first()
        if not usuario:
            logger.info(f"Jogador telegram_id={telegram_id} não encontrado no banco de dados.")
            return False

        sessoes = db.query(SessaoJogo).filter(SessaoJogo.id_usuario == usuario.id_usuario).all()
        for sessao in sessoes:
            db.query(HistoricoMensagens).filter(HistoricoMensagens.id_sessao == sessao.id_sessao).delete()
            estado = db.query(EstadoSessao).filter(EstadoSessao.id_sessao == sessao.id_sessao).first()
            if estado:
                estado.variaveis_jogo = {}
                estado.progresso_pedagogico = {}

        db.commit()
        logger.info(f"Sessão de jogo resetada com sucesso para telegram_id={telegram_id}")
        return True
