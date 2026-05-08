-- inventory/seed.sql
-- Category hierarchy seed data.
-- Uses INSERT OR IGNORE throughout — safe to re-run.

PRAGMA foreign_keys = ON;

-- ── Super categories ──────────────────────────────────────────────────────────

INSERT OR IGNORE INTO super_category (name) VALUES
    ('Food'),
    ('Clothing'),
    ('Sports'),
    ('Electronics'),
    ('Stationery'),
    ('Media, Collections & Keepsakes'),
    ('Cleaning'),
    ('Tools'),
    ('Bedding & Linen');

-- ── Mid categories ────────────────────────────────────────────────────────────

INSERT OR IGNORE INTO mid_category (name, super_category_id)
SELECT 'Media',                   id FROM super_category WHERE name = 'Media, Collections & Keepsakes';
INSERT OR IGNORE INTO mid_category (name, super_category_id)
SELECT 'Collections',             id FROM super_category WHERE name = 'Media, Collections & Keepsakes';
INSERT OR IGNORE INTO mid_category (name, super_category_id)
SELECT 'Keepsakes',               id FROM super_category WHERE name = 'Media, Collections & Keepsakes';
INSERT OR IGNORE INTO mid_category (name, super_category_id)
SELECT 'Power tools',             id FROM super_category WHERE name = 'Tools';
INSERT OR IGNORE INTO mid_category (name, super_category_id)
SELECT 'Hand tools',              id FROM super_category WHERE name = 'Tools';
INSERT OR IGNORE INTO mid_category (name, super_category_id)
SELECT 'Woodworking',             id FROM super_category WHERE name = 'Tools';
INSERT OR IGNORE INTO mid_category (name, super_category_id)
SELECT 'Plumbing & electrical',   id FROM super_category WHERE name = 'Tools';
INSERT OR IGNORE INTO mid_category (name, super_category_id)
SELECT 'Decorating & masonry',    id FROM super_category WHERE name = 'Tools';
INSERT OR IGNORE INTO mid_category (name, super_category_id)
SELECT 'Repair & fixing',         id FROM super_category WHERE name = 'Tools';

-- ── Leaf categories ───────────────────────────────────────────────────────────

-- Food
INSERT OR IGNORE INTO category (name, mid_category_id, super_category_id)
SELECT 'Dry food items', NULL, id FROM super_category WHERE name = 'Food';

-- Clothing
INSERT OR IGNORE INTO category (name, mid_category_id, super_category_id)
SELECT 'Winter / outdoor clothes', NULL, id FROM super_category WHERE name = 'Clothing';
INSERT OR IGNORE INTO category (name, mid_category_id, super_category_id)
SELECT 'Inner-layer / summer clothes', NULL, id FROM super_category WHERE name = 'Clothing';

-- Sports
INSERT OR IGNORE INTO category (name, mid_category_id, super_category_id)
SELECT 'Sports equipment', NULL, id FROM super_category WHERE name = 'Sports';

-- Electronics
INSERT OR IGNORE INTO category (name, mid_category_id, super_category_id)
SELECT 'Electronics', NULL, id FROM super_category WHERE name = 'Electronics';
INSERT OR IGNORE INTO category (name, mid_category_id, super_category_id)
SELECT 'Electrical equipment', NULL, id FROM super_category WHERE name = 'Electronics';
INSERT OR IGNORE INTO category (name, mid_category_id, super_category_id)
SELECT 'Cables', NULL, id FROM super_category WHERE name = 'Electronics';

-- Stationery
INSERT OR IGNORE INTO category (name, mid_category_id, super_category_id)
SELECT 'Stationery', NULL, id FROM super_category WHERE name = 'Stationery';

-- Media, Collections & Keepsakes
INSERT OR IGNORE INTO category (name, mid_category_id, super_category_id)
SELECT 'Books',
       (SELECT mc.id FROM mid_category mc JOIN super_category sc ON mc.super_category_id = sc.id WHERE mc.name = 'Media' AND sc.name = 'Media, Collections & Keepsakes'),
       (SELECT id FROM super_category WHERE name = 'Media, Collections & Keepsakes');
INSERT OR IGNORE INTO category (name, mid_category_id, super_category_id)
SELECT 'Music',
       (SELECT mc.id FROM mid_category mc JOIN super_category sc ON mc.super_category_id = sc.id WHERE mc.name = 'Media' AND sc.name = 'Media, Collections & Keepsakes'),
       (SELECT id FROM super_category WHERE name = 'Media, Collections & Keepsakes');
INSERT OR IGNORE INTO category (name, mid_category_id, super_category_id)
SELECT 'Films & TV',
       (SELECT mc.id FROM mid_category mc JOIN super_category sc ON mc.super_category_id = sc.id WHERE mc.name = 'Media' AND sc.name = 'Media, Collections & Keepsakes'),
       (SELECT id FROM super_category WHERE name = 'Media, Collections & Keepsakes');
INSERT OR IGNORE INTO category (name, mid_category_id, super_category_id)
SELECT 'Photographic collections',
       (SELECT mc.id FROM mid_category mc JOIN super_category sc ON mc.super_category_id = sc.id WHERE mc.name = 'Collections' AND sc.name = 'Media, Collections & Keepsakes'),
       (SELECT id FROM super_category WHERE name = 'Media, Collections & Keepsakes');
INSERT OR IGNORE INTO category (name, mid_category_id, super_category_id)
SELECT 'Games & puzzles',
       (SELECT mc.id FROM mid_category mc JOIN super_category sc ON mc.super_category_id = sc.id WHERE mc.name = 'Collections' AND sc.name = 'Media, Collections & Keepsakes'),
       (SELECT id FROM super_category WHERE name = 'Media, Collections & Keepsakes');
INSERT OR IGNORE INTO category (name, mid_category_id, super_category_id)
SELECT 'Gifted items',
       (SELECT mc.id FROM mid_category mc JOIN super_category sc ON mc.super_category_id = sc.id WHERE mc.name = 'Keepsakes' AND sc.name = 'Media, Collections & Keepsakes'),
       (SELECT id FROM super_category WHERE name = 'Media, Collections & Keepsakes');
INSERT OR IGNORE INTO category (name, mid_category_id, super_category_id)
SELECT 'Memory items',
       (SELECT mc.id FROM mid_category mc JOIN super_category sc ON mc.super_category_id = sc.id WHERE mc.name = 'Keepsakes' AND sc.name = 'Media, Collections & Keepsakes'),
       (SELECT id FROM super_category WHERE name = 'Media, Collections & Keepsakes');
INSERT OR IGNORE INTO category (name, mid_category_id, super_category_id)
SELECT 'Heirlooms',
       (SELECT mc.id FROM mid_category mc JOIN super_category sc ON mc.super_category_id = sc.id WHERE mc.name = 'Keepsakes' AND sc.name = 'Media, Collections & Keepsakes'),
       (SELECT id FROM super_category WHERE name = 'Media, Collections & Keepsakes');

-- Cleaning
INSERT OR IGNORE INTO category (name, mid_category_id, super_category_id)
SELECT 'Cleaning supplies', NULL, id FROM super_category WHERE name = 'Cleaning';
INSERT OR IGNORE INTO category (name, mid_category_id, super_category_id)
SELECT 'Cleaning equipment', NULL, id FROM super_category WHERE name = 'Cleaning';

-- Tools
INSERT OR IGNORE INTO category (name, mid_category_id, super_category_id)
SELECT 'Power tools',
       (SELECT mc.id FROM mid_category mc JOIN super_category sc ON mc.super_category_id = sc.id WHERE mc.name = 'Power tools' AND sc.name = 'Tools'),
       (SELECT id FROM super_category WHERE name = 'Tools');
INSERT OR IGNORE INTO category (name, mid_category_id, super_category_id)
SELECT 'General hand tools',
       (SELECT mc.id FROM mid_category mc JOIN super_category sc ON mc.super_category_id = sc.id WHERE mc.name = 'Hand tools' AND sc.name = 'Tools'),
       (SELECT id FROM super_category WHERE name = 'Tools');
INSERT OR IGNORE INTO category (name, mid_category_id, super_category_id)
SELECT 'Measuring & marking',
       (SELECT mc.id FROM mid_category mc JOIN super_category sc ON mc.super_category_id = sc.id WHERE mc.name = 'Hand tools' AND sc.name = 'Tools'),
       (SELECT id FROM super_category WHERE name = 'Tools');
INSERT OR IGNORE INTO category (name, mid_category_id, super_category_id)
SELECT 'Woodworking',
       (SELECT mc.id FROM mid_category mc JOIN super_category sc ON mc.super_category_id = sc.id WHERE mc.name = 'Woodworking' AND sc.name = 'Tools'),
       (SELECT id FROM super_category WHERE name = 'Tools');
INSERT OR IGNORE INTO category (name, mid_category_id, super_category_id)
SELECT 'Plumbing',
       (SELECT mc.id FROM mid_category mc JOIN super_category sc ON mc.super_category_id = sc.id WHERE mc.name = 'Plumbing & electrical' AND sc.name = 'Tools'),
       (SELECT id FROM super_category WHERE name = 'Tools');
INSERT OR IGNORE INTO category (name, mid_category_id, super_category_id)
SELECT 'Electrical',
       (SELECT mc.id FROM mid_category mc JOIN super_category sc ON mc.super_category_id = sc.id WHERE mc.name = 'Plumbing & electrical' AND sc.name = 'Tools'),
       (SELECT id FROM super_category WHERE name = 'Tools');
INSERT OR IGNORE INTO category (name, mid_category_id, super_category_id)
SELECT 'Decorating',
       (SELECT mc.id FROM mid_category mc JOIN super_category sc ON mc.super_category_id = sc.id WHERE mc.name = 'Decorating & masonry' AND sc.name = 'Tools'),
       (SELECT id FROM super_category WHERE name = 'Tools');
INSERT OR IGNORE INTO category (name, mid_category_id, super_category_id)
SELECT 'Masonry',
       (SELECT mc.id FROM mid_category mc JOIN super_category sc ON mc.super_category_id = sc.id WHERE mc.name = 'Decorating & masonry' AND sc.name = 'Tools'),
       (SELECT id FROM super_category WHERE name = 'Tools');
INSERT OR IGNORE INTO category (name, mid_category_id, super_category_id)
SELECT 'Sewing & repairs',
       (SELECT mc.id FROM mid_category mc JOIN super_category sc ON mc.super_category_id = sc.id WHERE mc.name = 'Repair & fixing' AND sc.name = 'Tools'),
       (SELECT id FROM super_category WHERE name = 'Tools');
INSERT OR IGNORE INTO category (name, mid_category_id, super_category_id)
SELECT 'Adhesives & fixings',
       (SELECT mc.id FROM mid_category mc JOIN super_category sc ON mc.super_category_id = sc.id WHERE mc.name = 'Repair & fixing' AND sc.name = 'Tools'),
       (SELECT id FROM super_category WHERE name = 'Tools');

-- Bedding & Linen
INSERT OR IGNORE INTO category (name, mid_category_id, super_category_id)
SELECT 'Duvets & pillows', NULL, id FROM super_category WHERE name = 'Bedding & Linen';
INSERT OR IGNORE INTO category (name, mid_category_id, super_category_id)
SELECT 'Bed linen', NULL, id FROM super_category WHERE name = 'Bedding & Linen';
INSERT OR IGNORE INTO category (name, mid_category_id, super_category_id)
SELECT 'Towels & bathroom linen', NULL, id FROM super_category WHERE name = 'Bedding & Linen';
INSERT OR IGNORE INTO category (name, mid_category_id, super_category_id)
SELECT 'Soft furnishings', NULL, id FROM super_category WHERE name = 'Bedding & Linen';

-- ── Sample locations ──────────────────────────────────────────────────────────
-- Edit these to match your actual house before running.

INSERT OR IGNORE INTO location (code, name, parent_id, level) VALUES
    ('KIT',  'Kitchen',  NULL, 'ROOM'),
    ('PAN',  'Pantry',   NULL, 'ROOM'),
    ('STU',  'Study',    NULL, 'ROOM'),
    ('BED',  'Bedroom',  NULL, 'ROOM'),
    ('GAR',  'Garage',   NULL, 'ROOM');

INSERT OR IGNORE INTO location (code, name, parent_id, level)
SELECT 'KIT-C1', 'Cupboard 1', id, 'FURNITURE' FROM location WHERE code = 'KIT';
INSERT OR IGNORE INTO location (code, name, parent_id, level)
SELECT 'KIT-C2', 'Cupboard 2', id, 'FURNITURE' FROM location WHERE code = 'KIT';
INSERT OR IGNORE INTO location (code, name, parent_id, level)
SELECT 'STU-BS1', 'Bookshelf 1', id, 'FURNITURE' FROM location WHERE code = 'STU';
INSERT OR IGNORE INTO location (code, name, parent_id, level)
SELECT 'STU-DD', 'Desk drawers', id, 'FURNITURE' FROM location WHERE code = 'STU';
INSERT OR IGNORE INTO location (code, name, parent_id, level)
SELECT 'GAR-SH', 'Shelving unit', id, 'FURNITURE' FROM location WHERE code = 'GAR';

INSERT OR IGNORE INTO location (code, name, parent_id, level)
SELECT 'KIT-C1-S1', 'Top shelf',    id, 'SHELF' FROM location WHERE code = 'KIT-C1';
INSERT OR IGNORE INTO location (code, name, parent_id, level)
SELECT 'KIT-C1-S2', 'Middle shelf', id, 'SHELF' FROM location WHERE code = 'KIT-C1';
INSERT OR IGNORE INTO location (code, name, parent_id, level)
SELECT 'KIT-C1-S3', 'Bottom shelf', id, 'SHELF' FROM location WHERE code = 'KIT-C1';
INSERT OR IGNORE INTO location (code, name, parent_id, level)
SELECT 'KIT-C2-S1', 'Top shelf',    id, 'SHELF' FROM location WHERE code = 'KIT-C2';
INSERT OR IGNORE INTO location (code, name, parent_id, level)
SELECT 'KIT-C2-S2', 'Middle shelf', id, 'SHELF' FROM location WHERE code = 'KIT-C2';
INSERT OR IGNORE INTO location (code, name, parent_id, level)
SELECT 'STU-BS1-S1', 'Top shelf',    id, 'SHELF' FROM location WHERE code = 'STU-BS1';
INSERT OR IGNORE INTO location (code, name, parent_id, level)
SELECT 'STU-BS1-S2', 'Middle shelf', id, 'SHELF' FROM location WHERE code = 'STU-BS1';
INSERT OR IGNORE INTO location (code, name, parent_id, level)
SELECT 'STU-BS1-S3', 'Bottom shelf', id, 'SHELF' FROM location WHERE code = 'STU-BS1';
INSERT OR IGNORE INTO location (code, name, parent_id, level)
SELECT 'GAR-SH-S1', 'Shelf 1', id, 'SHELF' FROM location WHERE code = 'GAR-SH';
INSERT OR IGNORE INTO location (code, name, parent_id, level)
SELECT 'GAR-SH-S2', 'Shelf 2', id, 'SHELF' FROM location WHERE code = 'GAR-SH';
