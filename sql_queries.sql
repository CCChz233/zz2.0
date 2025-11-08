-- ============================================
-- 数据库分类统计查询 SQL
-- ============================================

-- ========== 政策数据专项排查 ==========
-- 问题：政策数据为0，需要排查原因
-- 映射关系：policies (前端) → src_table='00_papers' (数据库)

-- 1. 检查 fact_events 表中政策数据（通过 src_table 过滤）
SELECT 
    'fact_events 表中的政策数据' as description,
    COUNT(*) as total_count,
    COUNT(CASE WHEN province_code IS NOT NULL THEN 1 END) as with_province,
    COUNT(CASE WHEN country_iso3 IS NOT NULL THEN 1 END) as with_country,
    COUNT(CASE WHEN province_code IS NULL AND country_iso3 IS NULL THEN 1 END) as no_geo_info,
    MIN(published_at) as earliest_date,
    MAX(published_at) as latest_date
FROM fact_events
WHERE src_table = '00_papers';

-- 2. 检查政策数据的地理分布（按省份）
SELECT 
    province_code,
    country_iso3,
    COUNT(*) as count
FROM fact_events
WHERE src_table = '00_papers'
  AND province_code IS NOT NULL
GROUP BY province_code, country_iso3
ORDER BY count DESC;

-- 3. 检查政策数据的时间分布（最近30天）
SELECT 
    DATE(published_at) as date,
    COUNT(*) as count
FROM fact_events
WHERE src_table = '00_papers'
  AND published_at >= NOW() - INTERVAL '30 days'
GROUP BY DATE(published_at)
ORDER BY date DESC;

-- 4. 检查原始源表 00_papers 是否有数据
SELECT 
    '00_papers 源表' as description,
    COUNT(*) as total_count,
    MIN(published_at) as earliest_date,
    MAX(published_at) as latest_date
FROM "00_papers";

-- 5. 对比 type 字段和 src_table 字段的分布
-- 注意：type 字段可能存储的是 'paper'，而查询时用的是 src_table='00_papers'
SELECT 
    type,
    src_table,
    COUNT(*) as count
FROM fact_events
WHERE src_table = '00_papers' OR type = 'paper' OR type = 'policies'
GROUP BY type, src_table
ORDER BY count DESC;

-- 6. 检查是否有政策数据但缺少地理编码
SELECT 
    '缺少地理信息的政策数据' as description,
    COUNT(*) as count,
    COUNT(CASE WHEN published_at >= NOW() - INTERVAL '7 days' THEN 1 END) as recent_7_days
FROM fact_events
WHERE src_table = '00_papers'
  AND (province_code IS NULL OR country_iso3 IS NULL);

-- 7. 综合诊断：一次性查看所有关键信息
WITH fact_stats AS (
    SELECT 
        'fact_events' as source,
        COUNT(*) as total,
        COUNT(CASE WHEN province_code IS NOT NULL THEN 1 END) as with_province,
        COUNT(CASE WHEN country_iso3 IS NOT NULL THEN 1 END) as with_country,
        MIN(published_at) as earliest,
        MAX(published_at) as latest
    FROM fact_events
    WHERE src_table = '00_papers'
),
source_stats AS (
    SELECT 
        '00_papers' as source,
        COUNT(*) as total,
        NULL::bigint as with_province,
        NULL::bigint as with_country,
        MIN(published_at) as earliest,
        MAX(published_at) as latest
    FROM "00_papers"
)
SELECT * FROM fact_stats
UNION ALL
SELECT * FROM source_stats;

-- ============================================

-- 1. fact_events 表按 type 字段分类统计（主要分类）
-- 显示：类型、数量、占比、最新记录时间
SELECT 
    type,
    COUNT(*) as count,
    ROUND(COUNT(*) * 100.0 / SUM(COUNT(*)) OVER (), 2) as percentage,
    MAX(published_at) as latest_published_at,
    MIN(published_at) as earliest_published_at
FROM fact_events
GROUP BY type
ORDER BY count DESC;

-- 2. fact_events 表按 src_table 字段分类统计（来源表）
-- 显示：来源表、数量、占比
SELECT 
    src_table,
    COUNT(*) as count,
    ROUND(COUNT(*) * 100.0 / SUM(COUNT(*)) OVER (), 2) as percentage
FROM fact_events
GROUP BY src_table
ORDER BY count DESC;

-- 3. fact_events 表按 type + src_table 交叉统计
-- 检查类型与来源表的对应关系
SELECT 
    type,
    src_table,
    COUNT(*) as count
FROM fact_events
GROUP BY type, src_table
ORDER BY type, count DESC;

-- 4. 地理分类统计（按国家）
-- 显示：国家ISO3、数量、占比
SELECT 
    COALESCE(country_iso3, 'NULL/未知') as country_iso3,
    COUNT(*) as count,
    ROUND(COUNT(*) * 100.0 / SUM(COUNT(*)) OVER (), 2) as percentage
FROM fact_events
GROUP BY country_iso3
ORDER BY count DESC
LIMIT 20;  -- 显示前20个国家

-- 5. 地理分类统计（按省份 - 仅中国）
-- 显示：省份代码、数量、占比
SELECT 
    province_code,
    COUNT(*) as count,
    ROUND(COUNT(*) * 100.0 / SUM(COUNT(*)) OVER (), 2) as percentage
FROM fact_events
WHERE country_iso3 = 'CHN' AND province_code IS NOT NULL
GROUP BY province_code
ORDER BY count DESC
LIMIT 35;  -- 显示前35个省份（覆盖所有省份）

-- 6. 原始表数据量统计（如果表存在）
-- 用于对比原始表和处理后的 fact_events 表的数据量
SELECT 
    '00_news' as table_name,
    COUNT(*) as count
FROM "00_news"
UNION ALL
SELECT 
    '00_competitors_news' as table_name,
    COUNT(*) as count
FROM "00_competitors_news"
UNION ALL
SELECT 
    '00_opportunity' as table_name,
    COUNT(*) as count
FROM "00_opportunity"
UNION ALL
SELECT 
    '00_papers' as table_name,
    COUNT(*) as count
FROM "00_papers"
ORDER BY count DESC;

-- 7. fact_events 表的时间分布统计
-- 按月份统计各类型的数据量
SELECT 
    DATE_TRUNC('month', published_at) as month,
    type,
    COUNT(*) as count
FROM fact_events
WHERE published_at IS NOT NULL
GROUP BY DATE_TRUNC('month', published_at), type
ORDER BY month DESC, type;

-- 8. 完整概览：按类型 + 国家 + 省份的统计
-- 显示最详细的三维分类统计
SELECT 
    type,
    COALESCE(country_iso3, 'NULL') as country_iso3,
    COALESCE(province_code, 'NULL') as province_code,
    COUNT(*) as count
FROM fact_events
GROUP BY type, country_iso3, province_code
ORDER BY type, count DESC
LIMIT 50;  -- 显示前50条组合

-- 9. 检查数据完整性：是否有类型缺失
SELECT 
    CASE 
        WHEN type IS NULL THEN 'type字段为空'
        WHEN type NOT IN ('news', 'competitor', 'opportunity', 'paper') THEN 'type值异常: ' || type
        ELSE '正常'
    END as status,
    COUNT(*) as count
FROM fact_events
GROUP BY status;

-- 10. 检查 src_table 与 type 的对应关系是否一致
-- 根据代码中的映射关系检查
SELECT 
    type,
    src_table,
    CASE 
        WHEN (type = 'news' AND src_table = '00_news') OR
             (type = 'competitor' AND src_table = '00_competitors_news') OR
             (type = 'opportunity' AND src_table = '00_opportunity') OR
             (type = 'paper' AND src_table = '00_papers')
        THEN '匹配'
        ELSE '不匹配'
    END as mapping_status,
    COUNT(*) as count
FROM fact_events
GROUP BY type, src_table, mapping_status
ORDER BY mapping_status, type;

