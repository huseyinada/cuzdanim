# Cüzdanım — Kurulum ve Telefona Yükleme Rehberi

Bu uygulama bir **web uygulaması (PWA)** olarak çalışır: bilgisayarda tarayıcıdan
açılır, Android telefonda ise **"Ana ekrana ekle"** ile normal bir uygulama gibi
kurulur — ikonu olur, tam ekran açılır ve **bildirim** alır. Her sabah 08:00'de
günün motivasyon mesajı ve o günkü harcama limitin telefonuna bildirim olarak gelir.

---

## 1) PC'de çalıştırma (en kolay yol)

1. `personal-finance-tracker` klasöründeki **`basla.bat`** dosyasına çift tıkla.
   - İlk seferde sanal ortamı (.venv) oluşturur ve paketleri kurar (1–2 dk).
   - Sonraki açılışlarda saniyeler içinde başlar.
   - Windows Güvenlik Duvarı "python.exe ağa erişsin mi?" diye sorarsa **İzin ver** de
     (telefonun aynı Wi-Fi'dan bağlanabilmesi için gerekli).
2. Tarayıcı otomatik açılır: **http://localhost:8000**
3. **Kayıt Ol** → ad, e-posta, şifre (en az 8 karakter, harf + rakam) → giriş yapılır.
4. **Plan** sekmesinden aylık gelirini (maaş) ve bu ay biriktirmek istediğin tutarı gir →
   uygulama sana günlük harcama limitini ve ay sonuna kadar gün gün çizelgeyi çıkarır.
5. **Bugün** sekmesinden harcamalarını ekle; limitin ve günün mesajı anlık güncellenir.

### Python kurmadan: Cüzdanım.exe
`derle.bat`'a çift tıkla → 2–4 dakika sonra **`dist\Cüzdanım.exe`** oluşur (~27 MB, tek dosya).
- Bu dosyayı istediğin klasöre kopyala ve çift tıkla: sunucu açılır, tarayıcı `http://localhost:8000`'e gider,
  pencerede telefonun için Wi-Fi adresi yazar.
- Veritabanı (`finance_tracker.db`), yedekler, `.env` ve bildirim anahtarları **.exe'nin yanındaki klasörde**
  oluşur; .exe'yi güncellediğinde verin korunur (şema otomatik güncellenir).
- Windows Defender/SmartScreen ilk açılışta "tanınmayan uygulama" diyebilir → **Ek bilgi → Yine de çalıştır**.
  (Bu, imzasız tüm yeni .exe'lerde görülen standart uyarıdır.)
- **Önemli:** .exe bir *Windows* programıdır; **Android telefonda çalışmaz.** WhatsApp'tan gönderirsen yalnızca
  başka bir PC'de açılır. Telefon için 2. ve 3. bölümlerdeki yolu izle (ana ekrana ekle / APK).

### VS Code kullanıyorsan
- `EZGİ_ELEKTRİK` klasörünü VS Code ile aç. `.vscode/settings.json` sayesinde açılan her
  terminalde **venv otomatik aktif** olur.
- Klasör açıldığında **"Kurulum (venv + paketler)"** görevi otomatik çalışır. İlk seferde
  VS Code "Allow Automatic Tasks?" diye sorar → **Allow** de.
- Çalıştırmak için: `Ctrl+Shift+B` (varsayılan build görevi = uvicorn başlatır) veya
  `F5` ile debug modunda başlat.

---

## 2) Telefonda kullanma — Seçenek A: Aynı Wi-Fi (hızlı test)

Bu yöntemde uygulama PC'de çalışır, telefon aynı Wi-Fi üzerinden bağlanır.
Sabah bildiriminin gelmesi için PC'nin o saatte açık ve uygulamanın çalışıyor olması gerekir.

1. `basla.bat` çalışırken pencerede **"Telefondan aç: http://192.168.x.x:8000"** satırını gör.
2. Telefonda **Chrome**'u aç ve bu adrese git. Uygulama açılıyorsa bağlantı tamam.
3. Bildirim ve "Ana ekrana ekle" için tarayıcı **HTTPS** ister. Yerel ağda HTTPS olmadığı için
   Chrome'a bu adrese güvenmesini söyle (tek seferlik):
   - Chrome adres satırına yaz: `chrome://flags/#unsafely-treat-insecure-origin-as-secure`
   - Kutuya PC adresini yaz: `http://192.168.x.x:8000` (kendi IP'n)
   - Seçeneği **Enabled** yap → **Relaunch**.
4. Uygulamayı tekrar aç → **Ayarlar → Bildirimleri Aç** → izin ver → **Test Bildirimi** ile dene.
5. Chrome menüsü (⋮) → **Ana ekrana ekle** / **Uygulamayı yükle**. Artık ana ekranda ikonu var.

> Not: Telefonun IP'si değişirse (farklı Wi-Fi) adres de değişir; PC'de sabit IP vermek işini kolaylaştırır.

---

## 3) Telefonda kullanma — Seçenek B: İnternet üzerinden, ücretsiz (önerilen)

Uygulamayı ücretsiz bir sunucuya koyarsan her yerden **https://** adresle açılır, PC kapalı olsa
da çalışır, bildirimler her sabah gelir. Yaklaşık 15 dakika sürer, kredi kartı gerekmez.

### 3.1 Ücretsiz veritabanı (Neon)
1. https://neon.tech → ücretsiz hesap → **New Project** (bölge: Frankfurt).
2. Açılan ekrandaki **Connection string**'i kopyala. Şuna benzer:
   `postgresql://kullanici:sifre@ep-xxx.eu-central-1.aws.neon.tech/neondb?sslmode=require&channel_binding=require`
3. İki küçük değişiklik yap (uygulamanın async sürücüsü için):
   - Başını `postgresql://` → **`postgresql+asyncpg://`**
   - Sonunu `?sslmode=require&channel_binding=require` → **`?ssl=require`**
   - Sonuç: `postgresql+asyncpg://kullanici:sifre@ep-xxx.eu-central-1.aws.neon.tech/neondb?ssl=require`

### 3.2 Bildirim anahtarlarını üret
PC'de proje klasöründe terminal aç (VS Code'da venv zaten aktif) ve çalıştır:
```
python -m app.tools.vapid
```
Çıkan `VAPID_PUBLIC_KEY=...` ve `VAPID_PRIVATE_KEY=...` satırlarını bir yere kopyala.

### 3.3 Kodu GitHub'a koy
1. https://github.com → **New repository** (private olabilir) → oluştur.
2. Proje klasöründe:
   ```
   git init
   git add .
   git commit -m "Cuzdanim"
   git branch -M main
   git remote add origin https://github.com/KULLANICI_ADIN/REPO_ADI.git
   git push -u origin main
   ```
   (`.gitignore` sayesinde `.env`, `.venv`, veritabanı ve anahtar dosyası yüklenmez.)

### 3.4 Render'a kur
1. https://render.com → GitHub ile giriş → **New → Blueprint** → repoyu seç.
   `render.yaml` otomatik okunur.
2. İstenen ortam değişkenlerini doldur:
   - `DATABASE_URL` → 3.1'de hazırladığın adres
   - `VAPID_PUBLIC_KEY`, `VAPID_PRIVATE_KEY` → 3.2'deki değerler
   - `VAPID_CLAIMS_EMAIL` → `mailto:senin@mailin.com`
3. **Apply**. 3–5 dakika sonra `https://cuzdanim-xxxx.onrender.com` gibi bir adres alırsın.
   İlk açılışta tablolar otomatik oluşturulur (`alembic upgrade head`).
4. Telefonda Chrome ile bu adresi aç → Kayıt ol → **Ayarlar → Bildirimleri Aç** →
   ⋮ menü → **Ana ekrana ekle**. Bitti 🎉

### 3.5 Önemli: Ücretsiz sunucu uyumasın
Render'ın ücretsiz planı 15 dk hareketsizlikte uygulamayı uyutur; uyuyan uygulama sabah
08:00 bildirimini gönderemez. Çözüm: ücretsiz bir "ping" servisi kur:
- https://cron-job.org → ücretsiz hesap → **Create cronjob**
- URL: `https://SENIN-ADRESIN.onrender.com/health` · Sıklık: **her 10 dakika**
Böylece uygulama sürekli uyanık kalır ve zamanlayıcı düzgün çalışır.

---

## 4) Gerçek bir APK istiyorsan (isteğe bağlı)

Seçenek B'deki https adresin hazır olduktan sonra:
1. https://www.pwabuilder.com → adresini yapıştır → **Start**.
2. **Package for stores → Android** → **Generate**. İndirilen zip içinde **`.apk`** dosyası var.
3. APK'yı telefona at, "Bilinmeyen kaynaklara izin ver" diyerek kur.
Bu APK, aynı web uygulamasını tam ekran açan resmi bir Android paketidir (Trusted Web Activity);
güncellemeler sunucudan otomatik gelir, tekrar APK kurman gerekmez.

---

## 5) Plan, kasa ve sabit giderler nasıl çalışır?

**Dönem seçimi (Plan sekmesi):** Maaşlıysan **Aylık**, haftalık para alıyorsan **Haftalık** seç
(hafta Pazartesi başlar). Gelirini ve kenara koymak istediğin birikimi gir.

- **Harcanabilir** = Gelir − Birikim hedefi
- **Sabitlere ayrılan** = Bu dönem henüz düşülmemiş sabit giderlerin toplamı (yemek, servis, kira…)
- **Bugün serbestçe harcayabilirsin** = (Harcanabilir − Bugüne kadar harcanan − Gelecek günlerin sabitleri) ÷ Kalan gün − Bugünün sabitleri
- Bir gün fazla harcarsan kalan günlerin limiti otomatik düşer; az harcarsan yükselir.

**Sabit giderler (Sabit sekmesi):** "Öğle yemeği · 150 ₺ · Her gün · 12:30" gibi kurallar tanımla.
- **Her gün / haftanın seçili günleri / ayda bir** tekrar; gün ve saat seçilir.
- Saati gelince **otomatik düşülür**: gerçek bir işlem olarak kaydedilir, kasa bakiyesi ve günlük
  limit anında güncellenir, telefonuna "Otomatik düşüldü 💸 … Kalan bakiye: …" bildirimi gelir.
- "Otomatik düş" kapalıysa yalnızca hatırlatma olur; **✔️ / Şimdi düş** ile elle düşersin.
- PC kapalı kaldıysa kaçırılan saatler (en fazla 7 gün geriye) açılışta telafi edilir; **aynı saat
  iki kez düşülemez** (veritabanı kısıtı).
- Kuralı silersen geçmiş kayıtlar silinmez.

**Kasa (Bugün sekmesi):** Toplam bakiye = tüm gelirler − tüm giderler. "+ Para ekle" ile maaş /
haftalık harçlığını gir; her harcama ve otomatik düşüm bakiyeyi görünür şekilde eksiltir.

**Zamanlayıcı:**
- **Her dakika**: Saati gelen sabit işlemler düşülür.
- **Sabah 08:00**: Günün motivasyon mesajı + bugünkü limit (bildirim).
- **Akşam 20:00**: Bir kategoride bütçenin %80'ini geçtiysen uyarı bildirimi.
- **Gece 03:30**: Veritabanı yedeği (`backups/` klasörü, son 14 yedek).
- **Her ayın 1'i 00:30**: Geçen ayın özeti kaydedilir.

Saatleri `.env` dosyasından değiştirebilirsin: `DAILY_MESSAGE_HOUR`, `BUDGET_CHECK_HOUR`.

**Veritabanı güvenliği:** Yabancı anahtar kısıtları zorunlu, WAL modu (çökmeye dayanıklı), her
açılışta otomatik şema güncellemesi (eski veritabanları dahil), Ayarlar'dan tek tıkla yedek.

---

## 6) Sık karşılaşılan sorunlar

| Sorun | Çözüm |
|---|---|
| Uygulamada **"Not Found"** / "Sunucu eski sürümde" uyarısı | Arka planda eski kodla çalışan bir `basla.bat` var. O pencereyi kapat, `basla.bat`'ı yeniden aç (artık kod değişince kendini yeniden yükler). Veri kaybolmaz. |
| Telefon `http://192.168…:8000` adresini açmıyor | PC ve telefon aynı Wi-Fi'da mı? Windows Güvenlik Duvarı python.exe'ye izin verdi mi? `basla.bat` çalışıyor mu? |
| "Bildirimleri Aç" → "Güvenli bağlantı gerekli" | Seçenek A'daki Chrome flag adımını uygula ya da Seçenek B ile https adresi kullan. |
| Bildirim izni verdim ama gelmiyor | Ayarlar → **Test Bildirimi**. Telefonda Chrome'un bildirim izni ve pil tasarrufu (Chrome kısıtlanmamış) kontrol et. |
| Render'da sabah mesajı gelmedi | 3.5'teki cron-job.org ping'ini kur; uygulama uyuyorsa zamanlayıcı çalışmaz. |
| Chart.js grafikleri boş | İlk açılışta internet gerekir (kütüphane CDN'den yüklenir, sonra çevrimdışı önbelleğe alınır). |
| Şifre kabul edilmiyor | En az 8 karakter, en az bir harf ve bir rakam. |
