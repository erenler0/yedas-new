# YEDAŞ × GSM Kesinti İzleme

Streamlit uygulaması: YEDAŞ planlı kesinti poligonlarını GSM sahalarının enlem/boylam noktalarıyla Shapely Point-in-Polygon ile çakıştırır, haritada gösterir, OSRM ile gerçek sürüş mesafesi hesaplar, arıza/akü sürelerini mum grafiğinde sunar.

Sahte saha verisi yoktur. SQLite şeması boş açılır; sahalar Admin Excel yüklemesiyle gelir.

## Çalıştırma

```bash
python -m venv .venv
.venv\Scripts\activate          # Windows
# source .venv/bin/activate     # Linux / macOS
pip install -r requirements.txt
streamlit run app.py
```

Ana dosya: `app.py` (Streamlit Community Cloud için aynı).

## Streamlit Community Cloud

1. Bu repoyu GitHub’a itin.
2. [share.streamlit.io](https://share.streamlit.io) üzerinde uygulamayı bağlayın.
3. Main file path: `app.py`
4. İsteğe bağlı Secrets:

```
ADMIN_PASSWORD = "admin5555"
```

Cloud diski geçicidir; yeniden başlatmada SQLite sıfırlanabilir. Kalıcı üretim için harici disk veya düzenli Excel senkronu kullanın.

## Eşleştirme

1. Birincil: YEDAŞ `coords` / `geoJson` poligonu ile saha `Latitude`/`Longitude` — Shapely `intersects` / `covers` (içeride veya sınırda).
2. Yedek: YEDAŞ `address` (il / ilçe / mahalle) ile Nominatim’den gelen saha adresi.

YEDAŞ API `st.cache_data(ttl=300)` ile 5 dakikada bir yenilenir.

## Admin

- Şifre (varsayılan): `admin5555`
- Excel sütunları: `KML Dosyası`, `Placemark Adı`, `Açıklama`, `Latitude`, `Longitude`, `Altitude`, `Koordinat (Ham)`
- Yeni sahalar Geopy Nominatim reverse geocoding ile İl / İlçe / Mahalle alır (`User-Agent` + 0.8 sn bekleme).
- İlçe merkezleri boş başlar; “6 il resmi ilçe merkezlerini yükle” veya elle ekleme.
- Saha varsayılan olarak coğrafi en yakın tek ilçe merkezine bağlanır; Admin override edebilir.
- OSRM sonuçları SQLite’da önbelleklenir.

## Dış servisler

| Servis | Kullanım |
| --- | --- |
| `https://www.yedas.com/api/planli-kesinti-harita` | Planlı kesinti |
| Nominatim (Geopy) | Reverse geocoding |
| `https://router.project-osrm.org` | Sürüş km / süre |

Nominatim kullanım politikasına uyun (özel User-Agent, rate limit). Yoğun OSRM için kendi OSRM örneğiniz önerilir.

## Performans optimizasyonları

Bu sürümde mevcut işlevler korunarak aşağıdaki darboğazlar giderilmiştir:

- Excel senkronunda 1300 saha için tek tek SQLite bağlantısı/upsert yerine bulk transaction kullanılır.
- Nominatim sonuçları koordinat bazlı kalıcı `geocode_cache` tablosunda saklanır; aynı koordinat ikinci kez sorgulanmaz.
- Shapely eşleştirmesinde tüm 1300 sahayı her poligonda taramak yerine `STRtree` spatial index kullanılır.
- YEDAŞ ana ekranında önce seçilen 1/3/7 günlük pencere filtrelenir, sonra Point-in-Polygon yapılır.
- Aynı Streamlit oturumunda aynı YEDAŞ snapshot'ı tekrar eşleştirilmez/yazılmaz.
- YEDAŞ eşleşme kayıtları SQLite'a toplu transaction ile yazılır.
- İlçe merkezine otomatik atamalar bulk update ile yapılır.
- OSRM cache'i 1300 ayrı SQLite sorgusu yerine tek toplu sorguyla okunur; yeni rotalar toplu yazılır.
- Analiz, arıza, saha ve ilçe listeleri kısa süreli Streamlit cache kullanır.
- Haritada aynı saha için tekrarlanan kırmızı/mavi marker'lar tekilleştirilir.
- SQLite bağlantılarında WAL yalnızca DB başlatılırken ayarlanır; kısa sorgular için `synchronous=NORMAL`, memory temp/cache ve busy timeout kullanılır.

### Nominatim notu

İlk kez 1300 benzersiz koordinat yükleniyorsa kamuya açık Nominatim servisinin rate limit'i nedeniyle reverse geocoding işlemi doğal olarak dakikalar sürebilir. Bu limit paralel isteklerle aşılmamalıdır. Optimizasyonun asıl amacı sonraki Excel senkronlarında aynı koordinatları tekrar sorgulamamaktır.
