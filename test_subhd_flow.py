import httpx, json, asyncio, re

async def test_full_flow():
    async with httpx.AsyncClient(timeout=httpx.Timeout(30), follow_redirects=True) as client:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/131.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        }
        
        search_url = "https://subhd.me/search/肖申克的救赎"
        print("=== Step 1: Search ===")
        resp = await client.get(search_url, headers=headers)
        print(f"Search Status: {resp.status_code}")
        print(f"Content length: {len(resp.text)}")
        
        ids = re.findall(r"/a/([a-zA-Z0-9]+)", resp.text)
        print(f"Found subtitle IDs: {ids[:5]}")
        
        if ids:
            sid = ids[0]
            print(f"\nUsing subtitle ID: {sid}")
            
            detail_url = f"https://subhd.me/a/{sid}"
            print(f"\n=== Step 2: Visit detail page ===")
            resp2 = await client.get(detail_url, headers=headers)
            print(f"Detail Status: {resp2.status_code}")
            
            down_url = f"https://subhd.me/down/{sid}"
            print(f"\n=== Step 3: Visit /down/ page ===")
            resp3 = await client.get(down_url, headers=headers)
            print(f"/down/ Status: {resp3.status_code}")
            print(f"/down/ Body preview: {resp3.text[:600]}")
            print(f"Cookies: {[(c.name, c.value[:30]) for c in client.cookies]}")
            
            api_headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/131.0.0.0 Safari/537.36",
                "Content-Type": "application/json",
                "Accept": "application/json, text/plain, */*",
                "Origin": "https://subhd.me",
                "Referer": down_url,
                "X-Requested-With": "XMLHttpRequest",
            }
            
            print(f"\n=== Step 4: prepare-download ===")
            try:
                resp4 = await client.post("https://subhd.me/api/sub/prepare-download", 
                                        json={"sid": sid},
                                        headers=api_headers)
                print(f"prepare-download Status: {resp4.status_code}")
                print(f"Body: {resp4.text[:300]}")
            except Exception as e:
                print(f"Error: {e}")
            
            print(f"\n=== Step 5: api/sub/down ===")
            try:
                resp5 = await client.post("https://subhd.me/api/sub/down", 
                                        json={"sid": sid, "cap": ""},
                                        headers=api_headers)
                print(f"api/sub/down Status: {resp5.status_code}")
                print(f"Body: {resp5.text[:500]}")
            except Exception as e:
                print(f"Error: {e}")

asyncio.run(test_full_flow())
