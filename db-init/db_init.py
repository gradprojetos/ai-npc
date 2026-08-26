import sqlite3

if __name__ == "__main__":
    conn = sqlite3.connect("game.db")
    cur = conn.cursor()
    cur.execute("CREATE TABLE IF NOT EXISTS usuario (id_usuario INTEGER PRIMARY KEY, nome VARCHAR(100), email VARCHAR(100), data_criacao TIMESTAMP DEFAULT CURRENT_TIMESTAMP)")
    cur.execute("CREATE TABLE IF NOT EXISTS npc (id_npc INTEGER PRIMARY KEY, nome VARCHAR(100), system_prompt TEXT, objetivo_pedagogico TEXT, metadata_npc JSONB)")
    conn.commit()
    conn.close()