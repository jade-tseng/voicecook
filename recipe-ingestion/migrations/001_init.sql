CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TABLE IF NOT EXISTS recipes (
    id               uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
    source_url       text        UNIQUE NOT NULL,
    url_hash         text        UNIQUE NOT NULL,
    title            text        NOT NULL,
    ingredients      jsonb       NOT NULL DEFAULT '[]',
    instructions     jsonb       NOT NULL DEFAULT '[]',
    servings         int,
    total_time_min   int,
    cuisine          text,
    difficulty       text,
    nutrition        jsonb,
    image_url        text,
    raw_html         text,
    parser_version   text        NOT NULL,
    search_vector    tsvector    GENERATED ALWAYS AS (
                                     to_tsvector('english', coalesce(title, ''))
                                 ) STORED,
    created_at       timestamptz DEFAULT now(),
    updated_at       timestamptz DEFAULT now()
);

CREATE TABLE IF NOT EXISTS recipe_name_aliases (
    id               bigserial   PRIMARY KEY,
    recipe_id        uuid        NOT NULL REFERENCES recipes(id) ON DELETE CASCADE,
    normalized_name  text        UNIQUE NOT NULL,
    original_name    text        NOT NULL,
    hit_count        int         DEFAULT 1,
    created_at       timestamptz DEFAULT now()
);

CREATE INDEX IF NOT EXISTS recipes_search_vector_gin
    ON recipes USING GIN (search_vector);

CREATE INDEX IF NOT EXISTS recipe_name_aliases_recipe_id_idx
    ON recipe_name_aliases (recipe_id);
