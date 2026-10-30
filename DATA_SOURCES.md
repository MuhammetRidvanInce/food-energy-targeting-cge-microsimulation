# Data provenance and access

## Public macroeconomic statistics

- Turkish Statistical Institute, **Supply and Use Tables and Input–Output Tables, 2023**: https://veriportali.tuik.gov.tr/tr/press/57943/metadata . Stage 1 retains the supplied public workbooks and mapping labels. The industry transformation follows Model D of the UN handbook: https://unstats.un.org/unsd/nationalaccount/docs/SUT_IOT_HB_Final_Cover.pdf .
- Turkish Statistical Institute, **Institutional Sector Accounts, 2024**, release containing the revised 2023 accounts: https://veriportali.tuik.gov.tr/tr/press/57929 . The direct-tax bridge uses the general-government resource entry D.5 for 2023.
- The SAM construction follows Hosoe, Gasawa and Hashimoto (2010), https://doi.org/10.1057/9780230281653 , and the related Turkish macro framework in İnce (2026), https://doi.org/10.3390/economies14100440 . Source books and copyrighted articles are not redistributed.

## Elasticity assignments

The three selected parameter sheets contain 64 Armington, 64 CET, and 64 factor-CES assignments, with their source and adaptation notes. They draw on GTAP's publicly documented behavioural parameters (Hertel and van der Mensbrugghe, 2024): https://gtap.agecon.purdue.edu/resources/res_display.asp?RecordID=7127 ; Turkish industry estimates by Kılıç and Yılmaz (2018): https://www.tek.org.tr/pdf/258_2412023_150743.pdf ; and the CET assumptions in İnce (2026). These are the model's selected numerical assignments, not a redistribution of the commercial GTAP database. English descriptions are provided in publication Table S1.

## Restricted household data

TurkStat **2024 Household Budget Survey** household, person and consumption records underpin the household split and microsimulation. Public release information is at https://veriportali.tuik.gov.tr/en/press/53957 ; research access must be arranged independently with TurkStat (https://www.tuik.gov.tr/). The repository includes filenames/schema usage in the code and aggregate calibration results. It excludes raw records, identifiers, individual incomes, fitted individual scores, and recipient-level simulation arrays. Access conditions and permission to use the source data continue to apply when reproducing the study.

## Aggregate outputs

Published tables, five-group SAM flows, sector results, simulated policy-level outcomes, binned distribution profiles and statistical diagnostics are included. Each supplementary workbook has Data and Variable Descriptions worksheets. Source statistical workbooks retain the terms and attribution requirements of their original providers; the MIT software license does not replace those terms.


Public statistical workbooks are English-labelled derivatives of the linked provider tables. Numerical cells and sector ordering are preserved; English labels do not imply an official provider translation. Original HBS filenames and field identifiers appear only in the access contract and code because authorised source records use that schema.
