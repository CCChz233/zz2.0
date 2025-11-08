-- 检查政策数据的地理编码情况
-- 问题：143条政策数据，但所有记录的 province_code 都为 NULL

-- 1. 检查是否有国家信息
SELECT 
    country_iso3,
    COUNT(*) as count
FROM fact_events
WHERE src_table = '00_papers'
GROUP BY country_iso3
ORDER BY count DESC;

-- 2. 检查 payload 中的地理信息来源
SELECT 
    payload->>'geo_source' as geo_source,
    payload->>'llm_country' as llm_country,
    payload->>'llm_province' as llm_province,
    COUNT(*) as count
FROM fact_events
WHERE src_table = '00_papers'
GROUP BY payload->>'geo_source', payload->>'llm_country', payload->>'llm_province'
ORDER BY count DESC
LIMIT 20;

-- 3. 查看一些示例数据，检查原始信息
SELECT 
    id,
    title,
    url,
    country_iso3,
    province_code,
    payload->>'llm_country' as llm_country,
    payload->>'llm_province' as llm_province,
    payload->>'geo_source' as geo_source,
    published_at
FROM fact_events
WHERE src_table = '00_papers'
ORDER BY published_at DESC
LIMIT 10;

-- 4. 检查是否有URL可以用来推断地理信息
SELECT 
    COUNT(*) as total,
    COUNT(CASE WHEN url LIKE '%.cn%' OR url LIKE '%gov.cn%' THEN 1 END) as cn_urls,
    COUNT(CASE WHEN url LIKE '%beijing%' OR url LIKE '%北京%' THEN 1 END) as beijing_urls,
    COUNT(CASE WHEN url LIKE '%shanghai%' OR url LIKE '%上海%' THEN 1 END) as shanghai_urls
FROM fact_events
WHERE src_table = '00_papers';

