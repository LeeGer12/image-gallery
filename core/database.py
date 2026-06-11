from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import sessionmaker

from config import DATABASE_URL
from core.models import Base

engine = create_engine(
    DATABASE_URL,
    pool_size=10,
    max_overflow=20,
    pool_pre_ping=True,
    echo=False,
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def rebuild_engine():
    """重建数据库引擎（配置变更后调用）。"""
    global engine, SessionLocal
    # 重新读取 config（可能已被 importlib.reload 更新）
    import importlib
    import config as cfg
    importlib.reload(cfg)

    if engine:
        engine.dispose()

    engine = create_engine(
        cfg.DATABASE_URL,
        pool_size=10,
        max_overflow=20,
        pool_pre_ping=True,
        echo=False,
    )
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def init_db():
    Base.metadata.create_all(bind=engine)
    _migrate_columns()
    _init_search_vector()


def _migrate_columns():
    """安全迁移：为已有数据库添加新列"""
    with engine.connect() as conn:
        conn.execution_options(isolation_level="AUTOCOMMIT")

        # users 表
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS users (
                id SERIAL PRIMARY KEY,
                username VARCHAR(64) NOT NULL UNIQUE,
                display_name VARCHAR(128),
                role VARCHAR(16) NOT NULL DEFAULT 'normal',
                is_active BOOLEAN DEFAULT TRUE,
                created_at TIMESTAMP DEFAULT NOW()
            )
        """))

        # operation_log 表
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS operation_log (
                id SERIAL PRIMARY KEY,
                user_id INTEGER NOT NULL REFERENCES users(id),
                action VARCHAR(64) NOT NULL,
                target_desc TEXT,
                created_at TIMESTAMP DEFAULT NOW()
            )
        """))

        # images 表新增列
        conn.execute(text("""
            ALTER TABLE images
            ADD COLUMN IF NOT EXISTS project_type VARCHAR(256)
        """))
        conn.execute(text("""
            ALTER TABLE images
            ADD COLUMN IF NOT EXISTS imported_by INTEGER REFERENCES users(id) ON DELETE SET NULL
        """))
        conn.execute(text("""
            ALTER TABLE images
            ADD COLUMN IF NOT EXISTS version INTEGER DEFAULT 1
        """))

        # albums 表新增列
        conn.execute(text("""
            ALTER TABLE albums
            ADD COLUMN IF NOT EXISTS created_by INTEGER REFERENCES users(id) ON DELETE SET NULL
        """))

        # operation_log.user_id 外键改为 ON DELETE SET NULL（允许删除用户后日志保留）
        conn.execute(text("""
            DO $$ BEGIN
                IF EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'operation_log_user_id_fkey') THEN
                    ALTER TABLE operation_log DROP CONSTRAINT operation_log_user_id_fkey;
                END IF;
            END $$;
        """))
        conn.execute(text("""
            ALTER TABLE operation_log
            ALTER COLUMN user_id DROP NOT NULL
        """))
        conn.execute(text("""
            ALTER TABLE operation_log
            ADD CONSTRAINT operation_log_user_id_fkey
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE SET NULL
        """))

        # users 表新增密码哈希列
        conn.execute(text("""
            ALTER TABLE users
            ADD COLUMN IF NOT EXISTS password_hash VARCHAR(256)
        """))

        conn.commit()


def _init_search_vector():
    """初始化 PostgreSQL 全文搜索 tsvector 列和触发器"""
    with engine.connect() as conn:
        conn.execution_options(isolation_level="AUTOCOMMIT")

        # 添加搜索向量列（如果不存在）
        conn.execute(text("""
            ALTER TABLE images
            ADD COLUMN IF NOT EXISTS search_vector tsvector
        """))

        # 创建 GIN 索引
        conn.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_images_search
            ON images USING GIN (search_vector)
        """))

        # 创建触发器函数：在插入或更新时自动更新 search_vector
        conn.execute(text("""
            CREATE OR REPLACE FUNCTION images_search_vector_update()
            RETURNS TRIGGER AS $$
            BEGIN
                NEW.search_vector :=
                    setweight(to_tsvector('simple', COALESCE(NEW.file_name, '')), 'A') ||
                    setweight(to_tsvector('simple', COALESCE(NEW.project_type, '')), 'B') ||
                    setweight(to_tsvector('simple', COALESCE(NEW.style_name, '')), 'B') ||
                    setweight(to_tsvector('simple', COALESCE(NEW.exif_json, '')), 'C');
                RETURN NEW;
            END;
            $$ LANGUAGE plpgsql;
        """))

        # 绑定触发器
        conn.execute(text("""
            DROP TRIGGER IF EXISTS images_search_vector_trigger ON images;
            CREATE TRIGGER images_search_vector_trigger
            BEFORE INSERT OR UPDATE ON images
            FOR EACH ROW
            EXECUTE FUNCTION images_search_vector_update();
        """))

        # 初始化现有数据
        conn.execute(text("""
            UPDATE images SET search_vector =
                setweight(to_tsvector('simple', COALESCE(file_name, '')), 'A') ||
                setweight(to_tsvector('simple', COALESCE(project_type, '')), 'B') ||
                setweight(to_tsvector('simple', COALESCE(style_name, '')), 'B') ||
                setweight(to_tsvector('simple', COALESCE(exif_json, '')), 'C')
            WHERE search_vector IS NULL;
        """))

        conn.commit()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
