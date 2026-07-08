CREATE TABLE IF NOT EXISTS clash_addresses (
    id SERIAL PRIMARY KEY,
    name VARCHAR(100) NOT NULL,
    url TEXT NOT NULL,
    is_active BOOLEAN DEFAULT FALSE NOT NULL,
    remark VARCHAR(255),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_clash_addresses_active ON clash_addresses(is_active);
CREATE INDEX IF NOT EXISTS idx_clash_addresses_created_at ON clash_addresses(created_at);
CREATE UNIQUE INDEX IF NOT EXISTS uq_clash_addresses_one_active
ON clash_addresses((is_active))
WHERE is_active = TRUE;
