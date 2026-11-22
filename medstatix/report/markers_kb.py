"""Built-in knowledge of common pharmacology / toxicology endpoints: which pathway each marker reports on and the
textbook sentences used to introduce and discuss that pathway. Only well-established, general statements."""
from __future__ import annotations

import re

PATHWAYS = {
    "oxidative": {
        "name": "oxidative stress",
        "patterns": [r"\bmda\b", r"malondialdehyde", r"\bsod\b", r"superoxide dismutase", r"\bcat\b", r"catalase",
                     r"\bgpx\b", r"glutathione peroxidase", r"\bgsh\b", r"reduced glutathione", r"\btac\b", r"\btas\b",
                     r"total antioxidant", r"\bno\b", r"nitric oxide", r"8-ohdg", r"lipid peroxid", r"\bros\b", r"\btbars\b"],
        "intro": ("Excessive generation of reactive oxygen species overwhelms endogenous antioxidant defences, causing "
                  "peroxidation of membrane lipids, oxidation of proteins and damage to DNA."),
        "discuss": ("Malondialdehyde is an end product of lipid peroxidation, whereas superoxide dismutase, catalase, "
                    "glutathione peroxidase and reduced glutathione form the first line of enzymatic and non-enzymatic "
                    "antioxidant defence; a rise in lipid peroxidation together with depletion of these defences is "
                    "therefore a recognised signature of oxidative injury."),
        "terms": ["oxidative stress", "malondialdehyde", "antioxidant", "lipid peroxidation", "superoxide dismutase"],
    },
    "nrf2": {
        "name": "Nrf2/HO-1 antioxidant signalling",
        "patterns": [r"nrf2", r"nrf-2", r"\bho-?1\b", r"heme oxygenase", r"haem oxygenase", r"keap1", r"nqo1"],
        "intro": ("Nuclear factor erythroid 2-related factor 2 (Nrf2) is the master regulator of the cellular antioxidant "
                  "response and drives the expression of cytoprotective genes such as haem oxygenase-1 (HO-1)."),
        "discuss": ("Activation of Nrf2 and its downstream target HO-1 up-regulates antioxidant and detoxifying enzymes, "
                    "so changes in this axis provide a mechanistic link between redox balance and tissue protection."),
        "terms": ["Nrf2", "heme oxygenase-1", "HO-1"],
    },
    "inflammation": {
        "name": "inflammation",
        "patterns": [r"tnf", r"\bil-?1", r"\bil-?6\b", r"\bil-?18\b", r"interleukin", r"nf-?κb", r"nf-?kb", r"cox-?2",
                     r"\binos\b", r"\bmpo\b", r"myeloperoxidase", r"\bcrp\b", r"\bnlrp3\b", r"tlr4", r"hmgb1"],
        "intro": ("Inflammation amplifies the initial injury: activation of nuclear factor-κB (NF-κB) induces pro-inflammatory "
                  "cytokines such as tumour necrosis factor-α (TNF-α), interleukin-1β (IL-1β) and interleukin-6 (IL-6), "
                  "which recruit leukocytes and propagate tissue damage."),
        "discuss": ("Pro-inflammatory cytokines and leukocyte infiltration form a self-amplifying loop with oxidative "
                    "stress, because activated leukocytes are themselves a major source of reactive oxygen species."),
        "terms": ["inflammation", "TNF-α", "interleukin", "NF-κB", "cytokine"],
    },
    "anti_inflammatory": {
        "name": "anti-inflammatory signalling",
        "patterns": [r"\bil-?10\b", r"\bil-?4\b", r"tgf-?β", r"tgf-?b"],
        "intro": "Anti-inflammatory mediators such as interleukin-10 (IL-10) limit the magnitude and duration of the inflammatory response.",
        "discuss": "Interleukin-10 restrains cytokine production by activated macrophages and contributes to the resolution of inflammation.",
        "terms": ["interleukin-10", "anti-inflammatory"],
    },
    "apoptosis": {
        "name": "apoptosis",
        "patterns": [r"\bbax\b", r"bcl-?2", r"caspase", r"\bcasp", r"cytochrome c", r"\bp53\b", r"apoptos", r"tunel",
                     r"bax/bcl"],
        "intro": ("Cells that survive the initial insult may undergo apoptosis through the mitochondrial pathway, which is "
                  "governed by the balance between pro-apoptotic Bax and anti-apoptotic Bcl-2 and executed by caspase-3."),
        "discuss": ("Bax promotes permeabilisation of the outer mitochondrial membrane and release of cytochrome c, whereas "
                    "Bcl-2 opposes it; an increased Bax/Bcl-2 balance therefore commits cells to caspase-dependent "
                    "apoptosis."),
        "terms": ["apoptosis", "Bax", "Bcl-2", "caspase-3"],
    },
    "kidney": {
        "name": "renal function",
        "patterns": [r"creatinine", r"\burea\b", r"\bbun\b", r"kim-?1", r"ngal", r"cystatin", r"uric acid"],
        "intro": "Serum creatinine and urea reflect glomerular filtration, whereas KIM-1 and NGAL are sensitive markers of tubular injury.",
        "discuss": ("Retention of creatinine and urea indicates reduced glomerular filtration, and tubular injury markers "
                    "such as KIM-1 and NGAL rise early after damage to the proximal tubule."),
        "terms": ["acute kidney injury", "creatinine", "KIM-1", "nephrotoxicity"],
    },
    "liver": {
        "name": "hepatic function",
        "patterns": [r"\balt\b", r"\bast\b", r"\balp\b", r"bilirubin", r"albumin", r"\bggt\b", r"transaminase"],
        "intro": "Leakage of the hepatocellular enzymes ALT and AST into the circulation is a standard index of hepatocyte injury.",
        "discuss": "Elevated serum ALT and AST indicate loss of hepatocyte membrane integrity, while altered bilirubin and albumin reflect impaired hepatic function.",
        "terms": ["hepatotoxicity", "liver injury", "aminotransferase"],
    },
    "cardiac": {
        "name": "myocardial injury",
        "patterns": [r"ck-?mb", r"troponin", r"\bctn", r"\bldh\b", r"lactate dehydrogenase"],
        "intro": "Release of cardiac troponins, CK-MB and LDH into the serum indicates myocardial cell damage.",
        "discuss": "Cardiac troponins and CK-MB are released when cardiomyocyte membranes are damaged and are standard indices of myocardial injury.",
        "terms": ["cardiotoxicity", "troponin", "myocardial injury"],
    },
    "muscle": {
        "name": "skeletal muscle injury",
        "patterns": [r"\bck\b", r"creatine kinase", r"myoglobin"],
        "intro": "Creatine kinase and myoglobin leak from damaged skeletal muscle fibres and are the usual circulating markers of muscle injury.",
        "discuss": "Circulating creatine kinase and myoglobin rise in proportion to the extent of skeletal muscle fibre damage.",
        "terms": ["skeletal muscle injury", "creatine kinase", "rhabdomyolysis"],
    },
}


def pathway_of(marker: str) -> str:
    m = marker.lower()
    for key, p in PATHWAYS.items():
        if any(re.search(rx, m) for rx in p["patterns"]):
            return key
    return "other"


def group_markers(markers: list[str]) -> dict:
    out = {}
    for mk in markers:
        out.setdefault(pathway_of(mk), []).append(mk)
    return out


# What each common marker reports on, one textbook sentence each. The Discussion uses only the sentences of the markers
# that were actually measured, so it never talks about an enzyme the study did not assay.
MARKER_ROLES = [
    (r"\bmda\b|malondialdehyde|tbars|lipid peroxid", "Malondialdehyde is a stable end product of lipid peroxidation and is the most widely used index of oxidative damage to membranes."),
    (r"\bgsh\b|reduced glutathione", "Reduced glutathione is the main non-enzymatic intracellular antioxidant; it is consumed directly by reactive oxygen species and as a cofactor of glutathione peroxidase, so its depletion indicates that antioxidant reserves have been exhausted."),
    (r"\bsod\b|superoxide dismutase", "Superoxide dismutase converts superoxide to hydrogen peroxide and is the first enzymatic barrier against oxidative injury."),
    (r"\bcat\b|catalase", "Catalase decomposes hydrogen peroxide to water and oxygen, preventing the formation of hydroxyl radicals."),
    (r"\bgpx\b|glutathione peroxidase", "Glutathione peroxidase reduces hydrogen peroxide and lipid hydroperoxides at the expense of reduced glutathione."),
    (r"\btac\b|\btas\b|total antioxidant", "Total antioxidant capacity summarises the combined activity of enzymatic and non-enzymatic antioxidants."),
    (r"\bno\b|nitric oxide|nitrite", "Large amounts of nitric oxide, produced mainly by inducible nitric oxide synthase in activated macrophages and neutrophils, react with superoxide to form peroxynitrite, which nitrates proteins and amplifies oxidative injury."),
    (r"\bmpo\b|myeloperoxidase", "Myeloperoxidase is stored in the azurophilic granules of neutrophils, so its tissue activity is a standard index of neutrophil infiltration; the hypochlorous acid it generates adds to the oxidative burden."),
    (r"tnf", "Tumour necrosis factor-α is released early by resident macrophages and drives the expression of adhesion molecules and further cytokines."),
    (r"\bil-?1", "Interleukin-1β is produced after inflammasome activation and is a potent amplifier of leukocyte recruitment."),
    (r"\bil-?6\b", "Interleukin-6 propagates the inflammatory response and the acute-phase reaction."),
    (r"\bil-?10\b", "Interleukin-10 restrains cytokine production by activated macrophages and contributes to the resolution of inflammation."),
    (r"nf-?κb|nf-?kb", "Nuclear factor-κB is the transcription factor that controls the expression of most pro-inflammatory cytokines and of inducible nitric oxide synthase."),
    (r"cox-?2", "Cyclo-oxygenase-2 is induced at sites of inflammation and generates pro-inflammatory prostaglandins."),
    (r"\binos\b", "Inducible nitric oxide synthase produces sustained, high levels of nitric oxide during inflammation."),
    (r"nrf2|nrf-2", "Nrf2 is the transcription factor that coordinates the expression of antioxidant and detoxifying enzymes."),
    (r"\bho-?1\b|heme oxygenase|haem oxygenase", "Haem oxygenase-1 degrades haem to biliverdin, carbon monoxide and iron and has antioxidant and anti-inflammatory actions."),
    (r"caspase", "Caspase-3 is the principal executioner caspase of apoptosis."),
    (r"\bbax\b", "Bax permeabilises the outer mitochondrial membrane and allows the release of cytochrome c."),
    (r"bcl-?2", "Bcl-2 opposes mitochondrial permeabilisation and protects cells from apoptosis."),
    (r"\balt\b|alanine aminotransferase", "Alanine aminotransferase is largely confined to hepatocytes, so its serum activity is a sensitive index of hepatocellular injury."),
    (r"\bast\b|aspartate aminotransferase", "Aspartate aminotransferase leaks from damaged hepatocytes and, to a lesser extent, from muscle."),
    (r"\balp\b|alkaline phosphatase", "Alkaline phosphatase rises mainly with cholestatic and biliary injury."),
    (r"creatinine", "Serum creatinine rises when glomerular filtration falls."),
    (r"\burea\b|\bbun\b", "Blood urea rises with reduced glomerular filtration and increased protein catabolism."),
    (r"kim-?1", "Kidney injury molecule-1 is shed from injured proximal tubular cells and is an early marker of tubular damage."),
    (r"ngal", "Neutrophil gelatinase-associated lipocalin is released early from injured renal tubules."),
    (r"ck-?mb", "CK-MB is released from damaged cardiomyocytes."),
    (r"troponin|\bctn", "Cardiac troponins are the most specific circulating markers of myocardial necrosis."),
    (r"\bldh\b|lactate dehydrogenase", "Lactate dehydrogenase leaks from cells whose membranes have been damaged and is a general index of cytotoxicity."),
]


def marker_role(marker: str) -> str:
    m = marker.lower()
    for rx, sentence in MARKER_ROLES:
        if re.search(rx, m):
            return sentence
    return ""
