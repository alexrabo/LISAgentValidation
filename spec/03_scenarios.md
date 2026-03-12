# Task 03 — Test Scenarios (Data Files)
**Output files:** `demo/harness/scenarios.csv`, `demo/harness/expected_outcomes.csv`  
**Depends on:** nothing  
**Global constraints:** see `IMPL_SPEC.md`

---

## Purpose
Ground truth data for the validation harness. Two CSV files — one with specimen values,
one with expected decisions. These are the "Diagnosis Tool" in Self-EvolveRec terms:
they must co-evolve with the knowledge graph if thresholds change.

**IMPORTANT:** These files encode clinical ground truth. Do not derive expected_decision
from running triage.py — derive from the scenario_type column:
- NORMAL → RELEASE
- CONTAMINATION → HOLD (safety_critical = true)
- SWAP → HOLD (safety_critical = true)
- CKD_NORMAL → RELEASE (this is the interference test — must NOT be HOLD)

---

## scenarios.csv

Source data: `lis-swap-contamination-triage/environment/data/visible_batch_nolabels.json`

```csv
specimen_id,patient_id,scenario_type,K,Ca,Na,Cl,HCO3,Glucose,prior_K_mean,prior_K_sd,prior_Ca_mean,prior_Ca_sd,prior_Na_mean,prior_Na_sd,prior_Cl_mean,prior_Cl_sd,prior_HCO3_mean,prior_HCO3_sd,prior_Glucose_mean,prior_Glucose_sd
S100,P001,NORMAL,4.15,9.42,140.3,103.2,24.1,94,4.1,0.25,9.4,0.35,140,2.5,103,2.0,24,2.0,92,12
S101,P002,CONTAMINATION,6.9,7.1,137.5,100.8,21.8,112,4.1,0.25,9.4,0.35,140,2.5,103,2.0,24,2.0,92,12
S102,P003,NORMAL,3.92,9.58,142.1,105.3,25.2,90,3.9,0.22,9.6,0.33,142,2.2,105,1.8,25,1.9,88,10
S103,P004,NORMAL,4.28,9.15,136.2,97.8,21.2,215,4.3,0.24,9.1,0.36,136,2.7,98,2.1,21,2.1,218,25
S104,P005,NORMAL,4.82,8.78,136.8,99.1,20.3,108,4.8,0.35,8.8,0.45,137,3.2,99,2.5,20,2.5,105,18
S105,P001,SWAP,4.31,9.12,135.9,98.1,21.0,221,4.1,0.25,9.4,0.35,140,2.5,103,2.0,24,2.0,92,12
S106,P004,SWAP,4.14,9.41,140.1,103.0,24.3,90,4.3,0.24,9.1,0.36,136,2.7,98,2.1,21,2.1,218,25
S107,P002,CONTAMINATION,6.2,7.8,137.9,101.1,22.0,111,4.1,0.25,9.4,0.35,140,2.5,103,2.0,24,2.0,92,12
S108,P003,NORMAL,3.88,9.62,141.8,104.8,25.0,87,3.9,0.22,9.6,0.33,142,2.2,105,1.8,25,1.9,88,10
S109,P005,NORMAL,4.75,8.85,137.2,98.8,19.8,103,4.8,0.35,8.8,0.45,137,3.2,99,2.5,20,2.5,105,18
S110,P011,CKD_NORMAL,6.10,7.95,138.1,101.2,22.1,94,5.6,0.30,7.9,0.30,138,2.5,101,2.0,22,2.0,95,10
```

---

## expected_outcomes.csv

```csv
specimen_id,expected_decision,safety_critical,scenario_type,notes
S100,RELEASE,false,NORMAL,baseline normal
S101,HOLD,true,CONTAMINATION,EDTA contamination — K+6.9 Ca+7.1
S102,RELEASE,false,NORMAL,normal
S103,RELEASE,false,NORMAL,diabetic patient — high Glucose is chronic not acute
S104,RELEASE,false,NORMAL,normal
S105,HOLD,true,SWAP,swap pair with S106 — specimens P001/P004 swapped
S106,HOLD,true,SWAP,swap pair with S105 — specimens P001/P004 swapped
S107,HOLD,true,CONTAMINATION,EDTA contamination — K+6.2 Ca+7.8
S108,RELEASE,false,NORMAL,normal
S109,RELEASE,false,NORMAL,normal
S110,RELEASE,false,CKD_NORMAL,CKD false-positive test — elevated K is chronic not acute. MUST be RELEASE.
```

---

## Acceptance Criteria

```bash
cd demo/harness
python3 -c "
import csv
with open('scenarios.csv') as f:
    rows = list(csv.DictReader(f))
assert len(rows) == 11, f'Expected 11 rows, got {len(rows)}'

with open('expected_outcomes.csv') as f:
    outcomes = {r['specimen_id']: r for r in csv.DictReader(f)}
assert outcomes['S110']['expected_decision'] == 'RELEASE', 'CKD test must be RELEASE'
assert outcomes['S101']['safety_critical'] == 'true', 'Contamination must be safety_critical'
assert outcomes['S105']['expected_decision'] == 'HOLD', 'Swap must be HOLD'
assert outcomes['S106']['expected_decision'] == 'HOLD', 'Swap pair must be HOLD'
print('PASS — 11 scenarios, CKD guard correct, swap pair correct')
"
```
