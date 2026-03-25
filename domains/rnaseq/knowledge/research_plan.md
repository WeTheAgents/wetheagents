# W∃A × nf-core/rnaseq: План исследования

**Статус:** v0.2 · Март 2026
**Подход:** Исследование → данные → предложение. Никаких утверждений до бенчмарка.

---

## Контекст

nf-core/rnaseq — пайплайн с 1200+ звёздами, 6800+ коммитами, десятилетней историей. Мейнтейнеры работают в Seqera Labs. Контрибьюторы включают авторов используемых инструментов. **Любая "находка" с вероятностью 90% уже обсуждалась.** Мы приходим учиться, исследовать и помогать — не "открывать баги".

---

## Чему нас научил self-roast

TrimGalore `process_high` (12 CPU) — **не баг**. Формула `cores = task.cpus - 4` учитывает реальный оверхед: чтение, запись, pigz-компрессия, валидация. Логика спроектирована совместно с автором TrimGalore (Felix Krueger) в nf-core/atacseq#65. Более того, автор сам показал что выше `--cores 2` (~6 CPU total) скорость не растёт.

**Вывод:** прежде чем утверждать что-либо — проверять историю Issues и PR. Для зрелого open-source проекта "очевидная" проблема = либо уже решена, либо не проблема.

---

## Исследовательские направления

Пять гипотез, упорядоченных по потенциалу и уверенности. Каждая — вопрос для бенчмарка, не утверждение.

### 1. fastp vs TrimGalore: есть ли значимая разница в wall-time?

**Гипотеза:** fastp быстрее TrimGalore при сопоставимом качестве тримминга.

**Что известно:**
- fastp написан на C++, TrimGalore — обёртка над Python-based Cutadapt
- fastp уже в пайплайне как опция (`--trimmer fastp`), TrimGalore — дефолт
- Литература заявляет 10-20x разницу, но на каких данных — неизвестно
- Автор TrimGalore показал что threading в Cutadapt упирается в потолок при 2 cores. fastp таких ограничений не имеет

**Что уже найдено в Issues:**
- Issue #1200: fastp ломает UMI-обработку Smart3-seq данных, TrimGalore работает корректно. Workaround: вернуться на TrimGalore. Это конкретная причина, почему fastp НЕ может быть дефолтом — он менее протестирован в edge cases
- fastp описан в docs как "fast, all-in-one preprocessing" с "multithreading support to achieve higher performance" — но не как замена TrimGalore

**Что НЕ известно:**
- Реальная разница на тестовых данных nf-core (крохотный геном → обе работают секунды?)
- Есть ли разница в качестве тримминга, которая влияет на downstream
- Масштаб: на 10 сэмплах vs на 500
- Есть ли ещё открытые баги fastp в пайплайне

**Бенчмарк:** запустить оба маршрута с `-with-trace`, сравнить wall-time, %CPU, peak_rss для TRIMGALORE vs FASTP процессов.

**Ожидаемый формат PR:** не "сменить дефолт" (есть баги с UMI, это политическое решение). Скорее: бенчмарк-данные + guidance в docs для пользователей без UMI, которым fastp подойдёт лучше. Или даже просто Issue с данными.

---

### 2. Picard MarkDuplicates vs samtools markdup

**Гипотеза:** samtools markdup быстрее Picard MarkDuplicates при меньшем потреблении памяти.

**Что известно из кода:**
- Picard MarkDuplicates — Java, однопоточный. Аллоцирует `task.memory * 0.8` через `-Xmx`. Ни одного аргумента для multi-threading
- samtools markdup — C, поддерживает `--threads`. Уже есть в nf-core/modules
- Picard — `process_medium` (6 CPU, 36GB). Использует 1 CPU + JVM heap. 5 CPU простаивают. Это НЕ как с TrimGalore — тут оверхеда нет, Java heap не использует остальные ядра
- `--skip_markduplicates` уже есть, но замены на samtools markdup нет

**Что уже найдено в Issues:**
- Issue #82: Picard MarkDuplicates падает с "No space left on device" из-за Java tmpdir. Известная проблема
- Issue #293: увеличение memory выше 8GB ломает Groovy парсинг. Исправлено, но показывает хрупкость Java-зависимости
- Issue #891: предложение скипать MarkDuplicates при UMI — принято
- Picard генерирует `.MarkDuplicates.metrics.txt` — этот формат интегрирован в MultiQC. Замена на samtools markdup потребует замены метрик
- Никто не предлагал samtools markdup как альтернативу (пока)

**Что НЕ известно:**
- Различается ли результат (помеченные дупликаты) между Picard и samtools? Если да — downstream эффект?
- Насколько критичен формат метрик Picard для MultiQC отчёта?
- Реальная разница в скорости и потреблении RAM

**Бенчмарк:** это нельзя сравнить просто переключателем пайплайна — нужен отдельный тест. Но в Issues никто это не предлагал, значит есть шанс на novel contribution. **Среднеприоритетно — требует глубокого понимания downstream.**

---

### 3. Профиль ресурсов: где пайплайн проводит время?

**Гипотеза:** Nextflow trace покажет, что значительная часть wall-time уходит не на alignment, а на QC и post-processing.

**Что известно:**
- Пайплайн запускает ~15 типов процессов, многие параллельно
- QC-процессы (RSeQC, Qualimap, dupRadar, Preseq, DESeq2, featureCounts, bigWig) — каждый отдельный контейнер, отдельный scheduling overhead
- Нет публичных данных о профиле времени по стадиям (или мы их не нашли)

**Что НЕ известно:**
- Реальное распределение wall-time по процессам на стандартных данных
- Какие процессы queue-bound (ждут ресурсы) vs compute-bound
- Есть ли низковисящий фрукт в scheduling/параллелизации

**Бенчмарк:** `-with-trace` + `-with-timeline` + `-with-report` на test профиле. Первичный результат — сама карта: "вот где время уходит". Ценно само по себе для сообщества.

---

### 4. SortMeRNA vs Bowtie2 vs BBDuk для rRNA removal

**Гипотеза:** Альтернативные инструменты rRNA removal быстрее SortMeRNA при сопоставимом качестве фильтрации.

**Что известно:**
- SortMeRNA — дефолт для `--remove_ribo_rna`
- Bowtie2 уже доступен: `--ribo_removal_tool bowtie2`
- RiboDetector (ML-based) доступен, но нестабилен в контейнерах
- BBDuk — быстрый, но не в пайплайне

**Что НЕ известно:**
- Реальная разница в скорости на стандартных данных
- Разница в false positive/negative rate (пропущенный rRNA vs неправильно удалённый non-rRNA)
- Почему SortMeRNA дефолт — возможно, качество фильтрации выше

**Бенчмарк:** запустить `--remove_ribo_rna` с SortMeRNA и с Bowtie2. Сравнить wall-time + количество отфильтрованных ридов.

**Ограничение:** test-профиль может не включать rRNA removal по дефолту. Нужно проверить.

---

### 5. I/O и компрессия: pigz, CRAM, стриминг

**Гипотеза:** параллельная компрессия и более компактные форматы экономят время на I/O-bound стадиях.

**Что известно:**
- pigz (параллельный gzip) уже используется TrimGalore при `--cores > 1`
- CRAM — 30-50% компактнее BAM, поддерживается SAMtools
- Пайплайн по умолчанию создаёт BAM, не CRAM

**Что НЕ известно:**
- Какая доля wall-time — I/O vs compute для каждого процесса
- Выиграет ли CRAM output на SSD vs HDD
- Есть ли downstream проблемы с CRAM (совместимость с QC инструментами)

**Приоритет:** низкий. Исследовать после получения базовой карты профиля (направление 3).

---

## План работ

### Этап 1: Базовый профиль (до Slack-велкома)

**Цель:** получить карту wall-time по процессам.

```bash
# Установить Nextflow
curl -s https://get.nextflow.io | bash

# Запуск с профилированием (дефолтная конфигурация)
nextflow run nf-core/rnaseq -r 3.23.0 \
  -profile test,docker \
  -with-trace trace_default.txt \
  -with-timeline timeline_default.html \
  -with-report report_default.html \
  --outdir results_default

# Запуск с fastp
nextflow run nf-core/rnaseq -r 3.23.0 \
  -profile test,docker \
  --trimmer fastp \
  -with-trace trace_fastp.txt \
  -with-timeline timeline_fastp.html \
  -with-report report_fastp.html \
  --outdir results_fastp
```

**Результат:** два trace-файла, два timeline HTML. Конкретные числа.

### Этап 2: Проверка Issues (до Slack-велкома)

**Уже выполнено частично.** Находки:

| Запрос | Результат |
|--------|-----------|
| fastp bugs | Issue #1200: fastp ломает UMI-обработку. TrimGalore — дефолт не случайно |
| Picard problems | Issues #82, #293, #895: Java memory/disk/locale проблемы. Известная боль |
| samtools markdup | Никто не предлагал как замену Picard. Потенциально novel |
| Performance profiling | Не найдено публичных trace-профилей. Потенциально ценно |

Ещё проверить:
- Closed issues с тегами "performance", "enhancement"
- CHANGELOG.md: когда и почему добавлялся fastp
- nf-core Slack archive (если доступен) по тем же запросам

### Этап 3: Slack-велком

Приходим с:
- "Вот профиль wall-time по стадиям на test-данных" (карта, не утверждение)
- "Вот разница fastp vs TrimGalore в нашем прогоне: X секунд vs Y секунд"
- "Мы хотели бы масштабировать этот бенчмарк на реальных данных. Это интересно? Что мы упускаем?"

### Этап 4: Глубокие бенчмарки (после ответа из Slack)

В зависимости от фидбека мейнтейнеров — масштабировать один из пяти направлений на реальные данные.

---

## Ограничения нашей машины

**Ryzen 5 4600H, 6C/12T, 24GB RAM**

| Профиль | RAM нужно | Наша машина | Возможно? |
|---------|-----------|-------------|-----------|
| test | 15GB cap | 24GB | ✅ |
| test_full (GRCh37 человек) | ~38GB для STAR | 24GB | ❌ |

Test-профиль использует крошечный геном. Разницы в скорости будут маленькие в абсолютных числах, но пропорции сохранятся. Для полноценного бенчмарка нужен cloud instance (32-64GB RAM) — но это этап 4, не этап 1.

---

## Велком-месседж (после получения данных)

```
Hi everyone 👋

I'm Sasha — software engineer, new to bioinformatics. A friend who
runs genomics pipelines at a medical data startup told me that full
nf-core/rnaseq runs can take days on large datasets, and I got
curious about where the time actually goes.

I ran the test profile with Nextflow trace (TrimGalore default vs
fastp). On test data the absolute numbers are small, but here's
what the profile looks like:

[вставить 5-6 строк из trace: процесс, wall-time, %CPU]

I'd like to scale this to a real dataset and see if the proportions
hold. Is this kind of profiling useful for the project? What would
be the most valuable thing to benchmark?

Thanks!
```

Ключевое: **данные вперёд, вопрос после.** Не "я нашёл проблему", а "вот что я измерил, что из этого интересно?"

---

## W∃A meta: чему учит этот домен

1. **Зрелый open-source ≠ неоптимизированный.** Каждая "очевидная" находка требует проверки: искали в Issues? Читали PR? Знаем контекст решения?

2. **Via negativa работает и тут.** Выкинуть ложные утверждения ценнее, чем генерировать новые гипотезы. Self-roast на TrimGalore сэкономил нам позор в публичном канале.

3. **Данные > мнения.** В биоинформатике (как и везде) "я думаю X быстрее Y" не стоит ничего. `trace.txt` с числами стоит PR.

4. **Первый контакт определяет всё.** Для W∃A первый merged PR в крупный проект — не техническое достижение, а репутационное. Лучше маленький data-driven вклад, чем амбициозный PR который не примут.
