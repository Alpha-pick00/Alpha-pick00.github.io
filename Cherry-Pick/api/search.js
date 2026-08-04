const NAVER_SHOPPING_ENDPOINT = 'https://openapi.naver.com/v1/search/shop.json';

export default async function handler(req, res) {
  if (req.method !== 'GET') {
    res.status(405).json({ error: 'Method not allowed' });
    return;
  }

  const query = typeof req.query.query === 'string' ? req.query.query.trim() : '';
  if (!query) {
    res.status(400).json({ error: 'Missing "query" parameter' });
    return;
  }

  const clientId = process.env.NAVER_CLIENT_ID;
  const clientSecret = process.env.NAVER_CLIENT_SECRET;
  if (!clientId || !clientSecret) {
    res.status(500).json({ error: 'Naver API credentials are not configured' });
    return;
  }

  const params = new URLSearchParams({
    query,
    display: '20',
    sort: 'asc',
  });

  let naverRes;
  try {
    naverRes = await fetch(`${NAVER_SHOPPING_ENDPOINT}?${params.toString()}`, {
      headers: {
        'X-Naver-Client-Id': clientId,
        'X-Naver-Client-Secret': clientSecret,
      },
    });
  } catch {
    res.status(502).json({ error: 'Failed to reach Naver API' });
    return;
  }

  if (!naverRes.ok) {
    const detail = await naverRes.text();
    res.status(naverRes.status).json({ error: 'Naver API request failed', detail });
    return;
  }

  const data = await naverRes.json();
  const items = (data.items ?? []).map((item) => ({
    id: item.productId,
    title: item.title.replace(/<\/?b>/g, ''),
    link: item.link,
    image: item.image,
    price: Number(item.lprice),
    mallName: item.mallName,
    brand: item.brand || null,
    category: [item.category1, item.category2, item.category3, item.category4]
      .filter(Boolean)
      .join(' > '),
  }));

  res.setHeader('Cache-Control', 's-maxage=300, stale-while-revalidate=60');
  res.status(200).json({ query, total: data.total, items });
}
