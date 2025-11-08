-- ============================================
-- 政策数据地理信息详细排查
-- 问题：143条政策数据，但所有记录的 province_code 都为 NULL
-- 需要检查：是否有国家信息、LLM返回了什么、URL/标题是否包含地理信息
-- ============================================

-- 1. 检查国家信息（country_iso3）分布
-- 看看是否有国家信息，哪怕没有省份
SELECT 
    '国家信息统计' as check_type,
    COALESCE(country_iso3, 'NULL/未知') as country_iso3,
    COUNT(*) as count,
    ROUND(COUNT(*) * 100.0 / SUM(COUNT(*)) OVER (), 2) as percentage
FROM fact_events
WHERE src_table = '00_papers'
GROUP BY country_iso3
ORDER BY count DESC;

-- 2. 检查 payload 中存储的 LLM 返回的地理信息
-- 这是最关键的：看看 LLM 到底返回了什么
SELECT 
    'LLM返回的地理信息' as check_type,
    COALESCE(payload->>'llm_country', 'NULL') as llm_country,
    COALESCE(payload->>'llm_province', 'NULL') as llm_province,
    COALESCE(payload->>'geo_source', 'NULL') as geo_source,
    COUNT(*) as count
FROM fact_events
WHERE src_table = '00_papers'
GROUP BY payload->>'llm_country', payload->>'llm_province', payload->>'geo_source'
ORDER BY count DESC
LIMIT 30;

-- 3. 检查实际的 country_iso3 和 payload 中的 llm_country 是否一致
-- 看看是否有国家信息但没有同步到主字段
SELECT 
    '地理信息同步情况' as check_type,
    country_iso3,
    payload->>'llm_country' as llm_country,
    payload->>'llm_province' as llm_province,
    province_code,
    COUNT(*) as count
FROM fact_events
WHERE src_table = '00_papers'
GROUP BY country_iso3, payload->>'llm_country', payload->>'llm_province', province_code
ORDER BY count DESC
LIMIT 30;

-- 4. 查看一些示例数据，检查原始信息
-- 看看 URL、标题中是否包含地理信息
SELECT 
    id,
    LEFT(title, 50) as title_preview,
    LEFT(url, 80) as url_preview,
    country_iso3,
    province_code,
    payload->>'llm_country' as llm_country,
    payload->>'llm_province' as llm_province,
    payload->>'geo_source' as geo_source,
    published_at
FROM fact_events
WHERE src_table = '00_papers'
ORDER BY published_at DESC
LIMIT 20;

-- 5. 检查 URL 中是否包含省份相关信息
-- 看看能否从 URL 推断出省份
SELECT 
    'URL中的省份信息' as check_type,
    CASE 
        WHEN url ILIKE '%beijing%' OR url ILIKE '%北京%' OR url ILIKE '%.bj.%' OR url ILIKE '%bj.gov.cn%' THEN '北京'
        WHEN url ILIKE '%shanghai%' OR url ILIKE '%上海%' OR url ILIKE '%.sh.%' OR url ILIKE '%sh.gov.cn%' THEN '上海'
        WHEN url ILIKE '%guangdong%' OR url ILIKE '%广东%' OR url ILIKE '%.gd.%' OR url ILIKE '%gd.gov.cn%' THEN '广东'
        WHEN url ILIKE '%zhejiang%' OR url ILIKE '%浙江%' OR url ILIKE '%.zj.%' OR url ILIKE '%zj.gov.cn%' THEN '浙江'
        WHEN url ILIKE '%jiangsu%' OR url ILIKE '%江苏%' OR url ILIKE '%.js.%' OR url ILIKE '%js.gov.cn%' THEN '江苏'
        WHEN url ILIKE '%hunan%' OR url ILIKE '%湖南%' OR url ILIKE '%.hn.%' OR url ILIKE '%hn.gov.cn%' THEN '湖南'
        WHEN url ILIKE '%gov.cn%' THEN '其他gov.cn'
        WHEN url ILIKE '%.cn%' THEN '其他.cn域名'
        ELSE '无明确省份信息'
    END as url_province_hint,
    COUNT(*) as count
FROM fact_events
WHERE src_table = '00_papers'
GROUP BY url_province_hint
ORDER BY count DESC;

-- 6. 检查标题中是否包含省份名称
-- 看看标题中是否有省份信息
SELECT 
    '标题中的省份信息' as check_type,
    CASE 
        WHEN title ILIKE '%北京%' OR title ILIKE '%北京市%' THEN '北京'
        WHEN title ILIKE '%上海%' OR title ILIKE '%上海市%' THEN '上海'
        WHEN title ILIKE '%广东%' OR title ILIKE '%广东省%' THEN '广东'
        WHEN title ILIKE '%浙江%' OR title ILIKE '%浙江省%' THEN '浙江'
        WHEN title ILIKE '%江苏%' OR title ILIKE '%江苏省%' THEN '江苏'
        WHEN title ILIKE '%湖南%' OR title ILIKE '%湖南省%' THEN '湖南'
        WHEN title ILIKE '%四川%' OR title ILIKE '%四川省%' THEN '四川'
        WHEN title ILIKE '%山东%' OR title ILIKE '%山东省%' THEN '山东'
        WHEN title ILIKE '%河南%' OR title ILIKE '%河南省%' THEN '河南'
        WHEN title ILIKE '%湖北%' OR title ILIKE '%湖北省%' THEN '湖北'
        WHEN title ILIKE '%安徽%' OR title ILIKE '%安徽省%' THEN '安徽'
        WHEN title ILIKE '%福建%' OR title ILIKE '%福建省%' THEN '福建'
        ELSE '无明确省份信息'
    END as title_province_hint,
    COUNT(*) as count
FROM fact_events
WHERE src_table = '00_papers'
GROUP BY title_province_hint
ORDER BY count DESC
LIMIT 35;

-- 7. 综合统计：看看有多少数据可以从 URL 或标题推断出省份
SELECT 
    '可推断省份的数据统计' as check_type,
    COUNT(*) as total,
    COUNT(CASE 
        WHEN url ILIKE '%beijing%' OR url ILIKE '%北京%' OR url ILIKE '%.bj.%' OR url ILIKE '%bj.gov.cn%'
          OR url ILIKE '%shanghai%' OR url ILIKE '%上海%' OR url ILIKE '%.sh.%' OR url ILIKE '%sh.gov.cn%'
          OR url ILIKE '%guangdong%' OR url ILIKE '%广东%' OR url ILIKE '%.gd.%' OR url ILIKE '%gd.gov.cn%'
          OR url ILIKE '%zhejiang%' OR url ILIKE '%浙江%' OR url ILIKE '%.zj.%' OR url ILIKE '%zj.gov.cn%'
          OR url ILIKE '%jiangsu%' OR url ILIKE '%江苏%' OR url ILIKE '%.js.%' OR url ILIKE '%js.gov.cn%'
          OR url ILIKE '%hunan%' OR url ILIKE '%湖南%' OR url ILIKE '%.hn.%' OR url ILIKE '%hn.gov.cn%'
          OR title ILIKE '%北京%' OR title ILIKE '%上海%' OR title ILIKE '%广东%' OR title ILIKE '%浙江%'
          OR title ILIKE '%江苏%' OR title ILIKE '%湖南%' OR title ILIKE '%四川%' OR title ILIKE '%山东%'
        THEN 1 
    END) as can_infer_from_url_or_title,
    COUNT(CASE WHEN country_iso3 IS NOT NULL THEN 1 END) as has_country,
    COUNT(CASE WHEN province_code IS NOT NULL THEN 1 END) as has_province
FROM fact_events
WHERE src_table = '00_papers';

-- 8. 查看一些具体案例，看看为什么没有提取到地理信息
-- 特别关注那些 URL 或标题中有省份信息但 province_code 为 NULL 的记录
SELECT 
    id,
    title,
    url,
    country_iso3,
    province_code,
    payload->>'llm_country' as llm_country,
    payload->>'llm_province' as llm_province,
    payload->>'geo_source' as geo_source,
    CASE 
        WHEN url ILIKE '%beijing%' OR url ILIKE '%北京%' OR url ILIKE '%.bj.%' THEN 'URL可能包含北京'
        WHEN url ILIKE '%shanghai%' OR url ILIKE '%上海%' OR url ILIKE '%.sh.%' THEN 'URL可能包含上海'
        WHEN url ILIKE '%guangdong%' OR url ILIKE '%广东%' OR url ILIKE '%.gd.%' THEN 'URL可能包含广东'
        WHEN url ILIKE '%zhejiang%' OR url ILIKE '%浙江%' OR url ILIKE '%.zj.%' THEN 'URL可能包含浙江'
        WHEN title ILIKE '%北京%' THEN '标题包含北京'
        WHEN title ILIKE '%上海%' THEN '标题包含上海'
        WHEN title ILIKE '%广东%' THEN '标题包含广东'
        WHEN title ILIKE '%浙江%' THEN '标题包含浙江'
        ELSE '无'
    END as geo_hint
FROM fact_events
WHERE src_table = '00_papers'
  AND province_code IS NULL
  AND (
    url ILIKE '%beijing%' OR url ILIKE '%北京%' OR url ILIKE '%.bj.%'
    OR url ILIKE '%shanghai%' OR url ILIKE '%上海%' OR url ILIKE '%.sh.%'
    OR url ILIKE '%guangdong%' OR url ILIKE '%广东%' OR url ILIKE '%.gd.%'
    OR url ILIKE '%zhejiang%' OR url ILIKE '%浙江%' OR url ILIKE '%.zj.%'
    OR title ILIKE '%北京%' OR title ILIKE '%上海%' OR title ILIKE '%广东%' OR title ILIKE '%浙江%'
  )
LIMIT 30;

