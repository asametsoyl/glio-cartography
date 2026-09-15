# Independent public-data validation: GSE331374

## Dataset and scope

- Source: NCBI GEO accession `GSE331374`, primary-tumor Visium sample `GSM9744831` and matched primary-tumor snRNA-seq sample `GSM9744835`.
- The series describes paired consecutive tissue slices from a BRAF V600E glioblastoma research case. The application does not infer or reconfirm that diagnosis.
- Input files were downloaded from GEO without modification. Patient identifiers are not used by the application; the run label was `GSE331374_PRIMARY`.
- Validation run date: 2026-09-15.

## End-to-end result

The full preprocessing, Tangram deconvolution, graph construction/training, visualization, HTML report, and PDF report path completed successfully on CPU.

| Measure | Result |
|---|---:|
| snRNA nuclei after QC | 1,644 |
| snRNA genes after QC | 15,161 |
| Visium spots after QC | 829 |
| Visium genes after QC | 14,872 |
| Annotated cell-type groups | 12 |
| Tangram fallback used | No |
| Tangram–NNLS average cell-type concordance | 0.3307 |
| GNN held-out cell-composition MSE | 0.01967 |
| Contact / diffuse graph edges | 2,104 / 17,120 |
| Detected ligand-receptor pairs | 96 / 150 |
| Ivy GAP signature diagonal mean correlation | 0.1735 |
| Ivy GAP signature top-1 zone correspondence | 0.60 |

## Interpretation boundaries

- Tangram–NNLS concordance is modest, so inferred cell proportions must be presented with uncertainty rather than as ground truth.
- The GNN target is derived from computational annotations; held-out MSE measures internal predictive consistency, not clinical validity.
- The Ivy GAP comparison is a gene-signature correspondence check against an external atlas, not histopathologist-labelled ground truth for this specimen.
- No follow-up cohort is supplied. The pipeline therefore does not produce Kaplan–Meier curves, median overall survival, or patient prognosis.
- Transcript abundance does not establish WHO grade, IDH mutation, or MGMT promoter methylation. The report marks these as not assessed and produces no patient-specific treatment recommendation.
- Compound names are literature-linked research hypotheses only; they are not efficacy predictions, prescriptions, or treatment recommendations.

## Reproduction inputs

- Visium matrix: `GSM9744831_primary_tumor_filtered_feature_bc_matrix.h5`
- Visium spatial archive: `GSM9744831_primary_tumor_spatial.tar.gz`
- snRNA-seq matrix: `GSM9744835_filtered_feature_bc_matrix_sn_primary_tumor.h5`
- Deconvolution method: Tangram with NNLS cross-method comparison
- GNN epochs for this validation run: 20

Primary provenance: https://www.ncbi.nlm.nih.gov/geo/query/acc.cgi?acc=GSE331374

Suggested multi-cohort follow-up: GSE237183 and GSE318562. These are not included in the metrics above.
