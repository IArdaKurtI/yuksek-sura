# Yüksek Şura

Yüksek Şura, üç farklı rolün ortak bir karara ulaştığı yapılandırılmış bir yapay zekâ akışıdır:

1. Stratejist uygulanabilir bir ilk taslak hazırlar.
2. Eleştirmen varsayımları, riskleri ve gözden kaçan seçenekleri sorgular.
3. Sentezleyici bulguları birleştirip nihai kararı üretir.

Siyah-beyaz masaüstü arayüzünde istenildiği kadar API bağlantısı eklenebilir. Her bağlantı Stratejist, Eleştirmen ve Sentezleyici rollerinden birine veya birkaçına atanabilir. Kalite eşiği geçilmezse sınırlı sayıda eleştiri/sentez turu daha çalışır.

## Windows'ta çalıştırma

Gerekenler:

- Standart 64-bit CPython 3.11 veya daha yenisi
- İnternet bağlantısı (ilk kurulum ve model çağrıları için)
- Kullanılacak sağlayıcılardan en az bir API anahtarı

`BASLAT.bat` dosyasına çift tıklayın. İlk çalıştırmada dosya:

- `.venv` ortamını oluşturur,
- gereken paketleri kurar,
- kurulum kontrolünden sonra masaüstü arayüzünü açar.

Uygulama altın Yüksek Şura amblemini pencere ve görev çubuğu ikonu olarak kullanır. Masaüstüne aynı ikonla **Yüksek Şura** kısayolu eklemek için `KISAYOL_OLUSTUR.bat` dosyasını bir kez çalıştırın.

Arayüzde **+ API EKLE** düğmesine basıp bağlantı adı, sağlayıcı, model, API anahtarı ve kullanılacağı rolleri girin. Her rol için en az bir aktif bağlantı bulunmalıdır. Aynı bağlantı üç role birden atanabilir.

Üst bardaki **TR / EN** seçicisi arayüz dilini anında değiştirir ve seçim sonraki açılışlar için kaydedilir. API bağlantı penceresi her açılışta ekranın merkezine yerleştirilir.

Roller bir API'nin Stratejist, Eleştirmen veya Sentezleyici aşamalarından hangilerinde kullanılacağını belirler. Genel açma/kapatma kontrolü API formunda değil, ana ekrandaki her bağlantı kartının sağ üstünde bulunur. Karttaki **AKTİF / PASİF** düğmesi bağlantıyı silmeden kilitler. Bilgiler kayıtlı kalır fakat pasifken hiçbir API çağrısına katılmaz. Yukarı/aşağı düğmeleri aynı roldeki fallback önceliğini belirler.

## API anahtarı güvenliği

- Anahtarlar arayüzde kayıttan sonra maskeli ve kilitli gösterilir.
- Anahtarlar düz metin olarak `.env`, çalışma kaydı veya log dosyasına yazılmaz.
- Windows DPAPI ile mevcut Windows kullanıcısına bağlı olarak şifrelenir.
- Bağlantı ayarları `%LOCALAPPDATA%\YuksekSura\connections.json` içinde tutulur.
- Çalışma kayıtları `%LOCALAPPDATA%\YuksekSura\runs` dizinine yazılır ve API anahtarı içermez.
- Bozuk ayar dosyasına karşı son sağlam bağlantı yedeği otomatik olarak denenir.

API anahtarlarını yine de kimseyle paylaşmayın. Başka bir Windows kullanıcısı şifrelenmiş dosyayı kendi hesabında açamaz.

## Dayanıklılık

Model çağrıları arka planda çalışır; ağ beklerken arayüz donmaz. **DURDUR** düğmesi devam eden işi iptal eder. Sağlayıcı, doğrulama veya kalite kapısı hataları uygulamayı kapatmak yerine sonuç panelinde kontrollü biçimde gösterilir. Uygulama günlükleri `%LOCALAPPDATA%\YuksekSura\logs` altında dönen, boyutu sınırlı dosyalarda saklanır.

Mutlak olarak hiçbir yazılım için “asla çökmez” garantisi verilemez; uygulama beklenen ağ, model, veri, dosya ve arayüz hata sınırlarını yakalayıp çalışmaya devam edecek şekilde tasarlanmıştır.

## Yapılandırma

Masaüstü arayüzündeki bağlantı ve model seçimi güvenli bağlantı deposundan gelir. Zaman aşımı, yeniden deneme, revizyon sayısı, kalite eşikleri ve bağlam sınırı için `.env` değerleri kullanılmaya devam eder. Başlangıç değerleri `.env.example` dosyasındadır. API anahtarı alanlarının masaüstü kullanımı için `.env` içinde doldurulması gerekmez.

`MAX_ATTEMPTS_PER_MODEL`, response mode sayısından bağımsız olarak her bağlantı için toplam fiziksel çağrı bütçesidir; schema/JSON/prompt geçişlerinde yeniden başlamaz.

Kalite kapısı güven ve revizyon işaretine ek olarak çözülememiş soru sayısını, eleştirmenin çelişkilerini ve `high`/`critical` risklerini deterministik olarak denetler. Son revizyon da kapıyı geçemezse sonuç yayımlanmaz; çalışma `quality_failed` durumuyla ve açık hata nedenleriyle sonlanır.

Arayüzde desteklenen hazır sağlayıcı seçenekleri OpenAI, Gemini, Anthropic, OpenRouter, Groq, Mistral ve DeepSeek'tir. `Custom` seçeneğiyle tam LiteLLM model adı ve isteğe bağlı API Base URL kullanılabilir. Aynı role atanmış sonraki aktif bağlantılar, önceki bağlantı başarısız olduğunda fallback olarak denenir.

## Komut satırı kullanımı

Komut satırı arayüzü geriye dönük uyumluluk için korunmuştur ve `.env` yapılandırmasını kullanır. `BASLAT.bat --cli` ile etkileşimli olarak açılabilir.

Masaüstü kurulum kontrolü (API çağrısı yapmaz):

```bat
.venv\Scripts\python.exe -m supreme_council.desktop --check
```

Tek komut satırı görevi:

```bat
.venv\Scripts\python.exe -m supreme_council.cli "Bir yatırım tezini güçlü ve zayıf yönleriyle değerlendir"
```

Görevi dosyadan okuyup tüm denetim kaydını saklama:

```bat
.venv\Scripts\python.exe -m supreme_council.cli --prompt-file gorev.txt --state-out runs\latest.json
```

## Geliştirici kurulumu ve test

```bat
py -3.12 -m venv .venv
.venv\Scripts\python.exe -m pip install -e ".[dev]"
.venv\Scripts\python.exe -m pytest -q --basetemp=.pytest-tmp
```

Kaynak için gerekli dosyalar `supreme_council/`, `tests/`, `main.py`, `pyproject.toml`, `.env.example`, `BASLAT.bat` ve bu README'dir. `.venv`, `__pycache__`, `.pytest_cache`, `.pytest-tmp` ve `*.egg-info` yeniden üretilebilen yerel artıklardır.
