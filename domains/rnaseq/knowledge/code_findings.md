# Находки из анализа кода nf-core/rnaseq v3.23.0

## Находка №1: TrimGalore тратит 4 CPU впустую на каждый сэмпл

**Файл:** `modules/nf-core/trimgalore/main.nf`, строка 1-19

```
label 'process_high'   ← выделяет 12 CPU, 72GB RAM
```

Но в скрипте TrimGalore:
```groovy
def cores = (task.cpus as int) - 4     // paired-end: 12 - 4 = 8
if (cores > 8) { cores = 8 }           // cap at 8
```

**Итого:** 12 CPU выделено, 8 используется максимум. **4 CPU простаивают на каждый сэмпл.**
72GB RAM выделено для процесса, который потребляет 2-4GB.

## Находка №2: fastp использует ресурсы эффективнее И работает быстрее

**Файл:** `modules/nf-core/fastp/main.nf`

```
label 'process_medium'   ← выделяет 6 CPU, 36GB RAM
--thread $task.cpus      ← использует ВСЕ выделенные CPU
```

fastp задокументирован как 10-20x быстрее TrimGalore в литературе.
При этом получает МЕНЬШЕ ресурсов (`process_medium` vs `process_high`).
И использует их ПОЛНОСТЬЮ (нет потерь на threading cap).

**Парадокс в коде:** более медленный инструмент (TrimGalore) получает БОЛЬШЕ ресурсов
и при этом ТЕРЯЕТ часть из них. Более быстрый (fastp) получает меньше и использует всё.

## Находка №3: TrimGalore — дефолт, fastp — опция

**Файл:** `nextflow.config`, строка 50

```groovy
trimmer = 'trimgalore'    // ← дефолт
```

Пользователи должны **явно** указать `--trimmer fastp` чтобы использовать быстрый вариант.
Большинство пользователей используют дефолт и не знают об альтернативе.

## Находка №4: Все тяжёлые процессы используют стандартные labels

| Процесс | Label | CPUs | RAM | Адекватность |
|---------|-------|------|-----|-------------|
| STAR_ALIGN | process_high | 12 | 72GB | ✅ Нужно 32-38GB для человека |
| TRIMGALORE | process_high | 12 | 72GB | ❌ Использует max 8 CPU, ~4GB RAM |
| SORTMERNA | process_high | 12 | 72GB | ⚠️ CPU ок, RAM сильно завышен |
| FASTP | process_medium | 6 | 36GB | ✅ Использует все CPU |
| SALMON_QUANT | process_medium | 6 | 36GB | ✅ Быстрый, ресурсов достаточно |
| SAMTOOLS_SORT | process_medium | 6 | 36GB | ⚠️ RAM завышен для sort |
| PICARD_MARKDUPLICATES | process_medium | 6 | 36GB | ⚠️ Java, медленнее samtools markdup |

## Находка №5: SortMeRNA как бутылочное горлышко

**Файл:** `modules/nf-core/sortmerna/main.nf`

```
label 'process_high'     ← 12 CPU, 72GB
--threads $task.cpus     ← использует все CPU
```

SortMeRNA — последовательный I/O-bound алгоритм. 12 CPU не помогут если bottleneck
в чтении/записи FASTQ. Альтернативы уже в пайплайне:
- `--ribo_removal_tool bowtie2` (быстрее для mapped filtering)
- RiboDetector (ML-based, но нестабилен в контейнерах)

## Находка №6: BAM_MARKDUPLICATES_SAMTOOLS subworkflow уже существует

**Дата:** 2026-03-19

**Субмодуль:** `subworkflows/nf-core/bam_markduplicates_samtools/main.nf`

Готовая цепочка из 4 шагов:
1. `SAMTOOLS_COLLATE` — name-sort для fixmate
2. `SAMTOOLS_FIXMATE` — добавляет mate-score tags
3. `SAMTOOLS_SORT` — coordinate sort
4. `SAMTOOLS_MARKDUP` — маркировка дупликатов

Интерфейс:
- Takes: `ch_bam`, `ch_fasta_fai`
- Emits: `bam`

**Отличия от Picard subworkflow:**
- Picard emits: `bam`, `cram`, `metrics`, `bai`, `crai`, `csi`, `stats`, `flagstat`, `idxstats`
- samtools emits: только `bam`
- Для полной замены нужно добавить: SAMTOOLS_INDEX + BAM_STATS_SAMTOOLS после markdup

**Текущее состояние в rnaseq pipeline:**
- Параметр `--markdup_tool` НЕ существует
- Есть только `--skip_markduplicates` (boolean)
- Три пути: Picard (default), UMI-dedup (with_umi=true), Parabricks (use_parabricks_star=true)
- Роутинг в `workflows/rnaseq/main.nf`:
  ```
  if (!params.skip_markduplicates && !params.with_umi && !markdups_done) {
      BAM_MARKDUPLICATES_PICARD(ch_genome_bam, ch_fasta, ch_fai)
      ch_genome_bam = BAM_MARKDUPLICATES_PICARD.out.bam
  }
  ```

**План PR:**
1. Добавить `params.markdup_tool = 'picard'` в nextflow.config
2. В main.nf: if markdup_tool == 'samtools' → BAM_MARKDUPLICATES_SAMTOOLS
3. Дополнить samtools subworkflow: + SAMTOOLS_INDEX + BAM_STATS_SAMTOOLS
4. Подключить samtools markdup stats к MultiQC
5. Тесты: CI с `--markdup_tool samtools`

## test_full Profile

**Файл:** `conf/test_full.config`
- Genome: GRCh37 (human)
- Pseudo-aligner: Salmon
- 8 paired-end samples: GM12878, K562, MCF7, H1 (x2 replicates)
- FASTQ source: `s3://ngi-igenomes/test-data/rnaseq/`
- skip_markduplicates: false (default) — Picard runs
