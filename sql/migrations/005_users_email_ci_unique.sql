-- Ensure users.email is normalized and unique (case-insensitive) for non-null values.

-- @statement
UPDATE users
SET email = NULL
WHERE email IS NOT NULL
  AND BTRIM(email) = '';

-- @statement
UPDATE users
SET email = LOWER(BTRIM(email))
WHERE email IS NOT NULL;

-- @statement
WITH ranked AS (
    SELECT
        id,
        LOWER(email) AS normalized_email,
        ROW_NUMBER() OVER (PARTITION BY LOWER(email) ORDER BY id) AS rn
    FROM users
    WHERE email IS NOT NULL
)
UPDATE users u
SET email = NULL
FROM ranked r
WHERE u.id = r.id
  AND r.rn > 1;

-- @statement
CREATE UNIQUE INDEX IF NOT EXISTS uq_users_email_ci_not_null
ON users ((LOWER(email)))
WHERE email IS NOT NULL;
