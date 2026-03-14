(function (global) {
    const phraseRules = [
        [/PSA Basal/g, "antígeno prostático específico basal (PSA)"],
        [/PSA Actual/g, "antígeno prostático específico actual (PSA)"],
        [/PSA Mediana/g, "mediana del antígeno prostático específico (PSA)"],
        [/PSA Control Tower/g, "torre de control del antígeno prostático específico"],
        [/Mayo Clinic Inspired/g, "referencia visual inspirada en la Clínica Mayo"],
        [/Mayo Clinic PSA Tower/g, "torre de control del antígeno prostático específico de la Clínica Mayo"],
        [/MSKCC Nomograms/g, "nomogramas del Centro Oncológico Memorial Sloan Kettering (MSKCC)"],
        [/CaPSURE Registry/g, "registro CaPSURE de evolución clínica"],
        [/OncoLens \/ PCaGuard/g, "plataformas oncológicas de apoyo clínico"],
        [/Patient Journey/g, "trayectoria clínica del paciente"],
        [/Journey Clínico del Paciente/g, "trayectoria clínica del paciente"],
        [/Nadir PSA/g, "nadir del antígeno prostático específico (PSA)"],
        [/% Cambio PSA/g, "% de cambio del antígeno prostático específico (PSA)"],
        [/Respuesta PSA/g, "respuesta del antígeno prostático específico (PSA)"],
        [/Volumen de Enfermedad \(CHAARTED\)/g, "volumen de enfermedad según el estudio CHAARTED"],
        [/Riesgo \(LATITUDE\)/g, "clasificación de riesgo según el estudio LATITUDE"],
        [/Líneas de Investigación — Evidencia Actual 2024-2026/g, "líneas de investigación con evidencia clínica estructurada"],
        [/Waterfall/g, "gráfico de cascada"],
        [/Clinical summary/g, "resumen clínico"],
        [/Treatment/g, "tratamiento"],
        [/Follow-up/g, "seguimiento"],
        [/Biochemical recurrence/g, "recurrencia bioquímica"],
        [/Perfil Biológico & Laboratorios \(Basal\)/g, "perfil biológico y laboratorios basales"],
        [/Estadificación & Volumen de Enfermedad/g, "estadificación y volumen de enfermedad"],
        [/Medicina de Precisión & Función/g, "medicina de precisión y función"],
        [/Sitio de Metástasis \(Predominante\)/g, "sitio de metástasis predominante"],
        [/Panel Genético Realizado/g, "panel genético realizado"],
        [/Línea Terapéutica/g, "línea terapéutica"],
        [/Esquema \(Fármacos\)/g, "esquema farmacológico"],
        [/Comorbilidades Críticas \(Contraindicaciones\)/g, "comorbilidades críticas y contraindicaciones"],
        [/Historial Terapéutico Previo \(Opcional\)/g, "historial terapéutico previo (opcional)"],
        [/Perfil Demográfico México \(Investigación\)/g, "perfil demográfico de México para investigación"],
        [/Paquetes-Año/g, "paquetes-año"],
        [/Sx\. Metabólico/g, "síndrome metabólico"],
        [/Dx:/g, "Fecha de diagnóstico:"],
        [/SS:/g, "Seguridad social:"],
        [/Toxicidad \(CTCAE\)/g, "toxicidad según los Criterios Comunes de Terminología para Eventos Adversos"],
        [/Eventos Esqueléticos \(SREs\)/g, "eventos esqueléticos relacionados"],
        [/Escala Dolor/g, "escala de dolor"],
        [/1\. Identidad del Paciente \(NSS\)/g, "1. Identidad del paciente (número de seguridad social, NSS)"],
        [/NSS \(11 Dígitos\)/g, "Número de seguridad social (NSS) de 11 dígitos"],
        [/M0 - No Metastásico/g, "Sin metástasis a distancia (M0)"],
        [/Clasificación CHAARTED \(Volumen\)/g, "Clasificación de volumen según CHAARTED"],
        [/Status HRR \(BRCA\/ATM\)/g, "Estado de reparación por recombinación homóloga (HRR) con genes BRCA y ATM"],
        [/Status MSI \(Inestabilidad\)/g, "Estado de inestabilidad microsatelital (MSI)"],
        [/Sensible a Hormonas \(mHSPC\)/g, "Enfermedad metastásica sensible a la castración (mHSPC)"],
        [/Resistente a Castración \(mCRPC\)/g, "Enfermedad resistente a la castración metastásica (mCRPC)"],
        [/Fosfatasa Alc\./g, "Fosfatasa alcalina"],
        [/Gammagrama Óseo Disponible/g, "Gammagrama óseo disponible"],
        [/Evitar Enza\/Apa/g, "Evitar Enzalutamida o Apalutamida"],
        [/Precaución Abi/g, "Precaución con Abiraterona"],
        [/Clase C \(Severo - Contraindica Abi\/Doce\)/g, "Clase C (severo, contraindica Abiraterona o Docetaxel)"],
        [/PSA tracking/g, "seguimiento del antígeno prostático específico"],
        [/AI prediction/g, "predicción asistida por inteligencia artificial"],
        [/Risk trajectory/g, "trayectoria de riesgo"],
        [/Alertas auto/g, "alertas automáticas"],
        [/Research export/g, "exportación para investigación"],
        [/Cohorte analytics/g, "analítica de cohortes"],
        [/Multi-site/g, "multisitio"],
        [/Trial matching/g, "emparejamiento con ensayos clínicos"],
        [/Patient portal/g, "portal del paciente"],
        [/Salvage RT/g, "radioterapia de rescate"],
        [/Status/g, "Estado actual"],
        [/Pre-biopsia/g, "prebiopsia"],
        [/pre-RP/g, "previos a prostatectomía radical"],
        [/Post-RP/g, "posteriores a prostatectomía radical"],
        [/QoL/g, "calidad de vida"],
        [/PROs/g, "resultados reportados por el paciente (PROs)"],
        [/PRO ASSESSMENT/g, "evaluación de resultados reportados por el paciente"],
        [/Patient-Reported Outcomes/g, "resultados reportados por el paciente"],
        [/\bStatus\b/g, "Estado"],
    ];

    const tokenRules = [
        [/\bpsadt_months\b/g, "tiempo de duplicación del antígeno prostático específico"],
        [/\bpsa_current\b/g, "antígeno prostático específico actual"],
        [/\bpsa_postop\b/g, "antígeno prostático específico posoperatorio"],
        [/\bPSADT\b(?!\))/g, "tiempo de duplicación del antígeno prostático específico (PSADT)"],
        [/\bPSAD\b(?!\))/g, "densidad del antígeno prostático específico (PSAD)"],
        [/\bPSA\b(?!\))/g, "antígeno prostático específico (PSA)"],
        [/\bBCR2\b(?!\))/g, "segunda recurrencia bioquímica (BCR2)"],
        [/\bBCR\b(?!\))/g, "recurrencia bioquímica (BCR)"],
        [/\bAS\b(?!\))/g, "vigilancia activa (AS)"],
        [/\bADT\b(?!\))/g, "terapia de privación androgénica (ADT)"],
        [/\bARPI\b(?!\))/g, "inhibidor de la vía del receptor androgénico (ARPI)"],
        [/\bPARPi\b(?!\))/g, "inhibidor de PARP (PARPi)"],
        [/(?<![-\w])RT\b(?!\))/g, "radioterapia (RT)"],
        [/\bECOG\b(?!\))/g, "estado funcional del Grupo Cooperativo Oncológico del Este (ECOG)"],
        [/\bHRR\b(?!\))/g, "reparación por recombinación homóloga (HRR)"],
        [/\bMSI-H\b(?!\))/g, "inestabilidad microsatelital alta (MSI-H)"],
        [/\bMSI\b(?![-\w]|\))/g, "inestabilidad microsatelital (MSI)"],
        [/\bPSMA-PET\/CT\b(?!\))/g, "tomografía por emisión de positrones y tomografía computarizada dirigidas al antígeno prostático específico de membrana (PSMA-PET/CT)"],
        [/\bPSMA-PET\b(?!\))/g, "tomografía por emisión de positrones dirigida al antígeno prostático específico de membrana (PSMA-PET)"],
        [/\bPSMA\b(?![-\w]|\))/g, "antígeno prostático específico de membrana (PSMA)"],
        [/\bmHSPC\b(?!\))/g, "enfermedad metastásica sensible a la castración (mHSPC)"],
        [/\bmCRPC\b(?!\))/g, "enfermedad resistente a la castración metastásica (mCRPC)"],
        [/\bM0 CRPC\b(?!\))/g, "enfermedad resistente a la castración sin metástasis (M0 CRPC)"],
        [/\bM1 CRPC\b(?!\))/g, "enfermedad resistente a la castración con metástasis (M1 CRPC)"],
        [/\bCRPC\b(?!\))/g, "enfermedad resistente a la castración (CRPC)"],
        [/\bIPSS\b(?!\))/g, "puntaje internacional de síntomas prostáticos (IPSS)"],
        [/\bIIEF-5\b(?!\))/g, "índice internacional de función eréctil de 5 preguntas (IIEF-5)"],
        [/\bBPI\b(?!\))/g, "inventario breve del dolor (BPI)"],
        [/\bEQ-5D\b(?!\))/g, "cuestionario EQ-5D"],
        [/\bVAS\b(?!\))/g, "escala visual analógica (VAS)"],
        [/\bFACT-P\b(?!\))/g, "cuestionario FACT-P"],
        [/\bLDH\b(?!\))/g, "lactato deshidrogenasa (LDH)"],
        [/\bALP\b(?!\))/g, "fosfatasa alcalina (ALP)"],
        [/\bRP\b(?!\))/g, "prostatectomía radical (RP)"],
        [/\bSBRT\b(?!\))/g, "radioterapia corporal estereotáctica (SBRT)"],
        [/\bMDT\b(?!\))/g, "terapia dirigida a metástasis (MDT)"],
        [/\bAI\b(?!\))/g, "inteligencia artificial (AI)"],
        [/\bCaP\b(?!\))/g, "cáncer de próstata (CaP)"],
        [/\bCDISC\b(?!\))/g, "estándares del Consorcio de Estándares para el Intercambio de Datos Clínicos (CDISC)"],
        [/\bDM2\b(?!\))/g, "diabetes mellitus tipo 2"],
        [/\bHTA\b(?!\))/g, "hipertensión arterial"],
        [/\bSREs\b(?!\))/g, "eventos esqueléticos relacionados"],
        [/\bSRE\b(?!\))/g, "evento esquelético relacionado"],
        [/\bCTCAE\b(?!\))/g, "Criterios Comunes de Terminología para Eventos Adversos (CTCAE)"],
        [/\bPFS\b(?!\))/g, "supervivencia libre de progresión (PFS)"],
        [/\bAUC\b(?!\))/g, "área bajo la curva (AUC)"],
        [/\bNLP\b(?!\))/g, "procesamiento de lenguaje natural (NLP)"],
        [/\bML\b(?!\))/g, "aprendizaje automático (ML)"],
        [/\bUSA\b(?!\))/g, "Estados Unidos"],
        [/\bMSS\b(?!\))/g, "estable a nivel microsatelital"],
        [/(?<!panel )\bPROS-([A-Z0-9]+)\b/g, "panel PROS-$1 de la guía de la Red Nacional Integral del Cáncer (NCCN)"],
        [/(?<!estudio )\bCHAARTED\b/g, "estudio CHAARTED"],
        [/(?<!estudio )\bLATITUDE\b/g, "estudio LATITUDE"],
        [/(?<!estudio )\bARASENS\b/g, "estudio ARASENS"],
        [/(?<!estudio )\bPEACE-1\b/g, "estudio PEACE-1"],
        [/(?<!estudio )\bEMBARK\b/g, "estudio EMBARK"],
        [/(?<!estudio )\bSPARTAN\b/g, "estudio SPARTAN"],
        [/(?<!estudio )\bARAMIS\b/g, "estudio ARAMIS"],
        [/(?<!estudio )\bPROSPER\b/g, "estudio PROSPER"],
        [/(?<!estudio )\bRAVES\b/g, "estudio RAVES"],
        [/(?<!estudio )\bRADICALS-RT\b/g, "estudio RADICALS-RT"],
        [/(?<!estudio )\bGETUG-AFU 16\b/g, "estudio GETUG-AFU 16"],
        [/(?<!estudio )\bRTOG 9601\b/g, "estudio RTOG 9601"],
        [/(?<!estudio )\bPROfound\b/g, "estudio PROfound"],
        [/(?<!estudio )\bVISION\b/g, "estudio VISION"],
        [/(?<!estudio )\bKEYNOTE-158\b/g, "estudio KEYNOTE-158"],
    ];

    function humanize(value) {
        if (typeof value !== "string") {
            return value;
        }
        let text = value;
        for (const [pattern, replacement] of phraseRules) {
            text = text.replace(pattern, replacement);
        }
        for (const [pattern, replacement] of tokenRules) {
            text = text.replace(pattern, replacement);
        }
        text = text.replace(/estudios estudio /g, "estudios ");
        text = text.replace(/según el estudio estudio /g, "según el estudio ");
        text = text.replace(/según los estudios estudio /g, "según los estudios ");
        return text.replace(/\s{2,}/g, " ").trim();
    }

    function normalizeAttribute(element, attribute) {
        const raw = element.getAttribute(attribute);
        if (!raw) {
            return;
        }
        const normalized = humanize(raw);
        if (normalized !== raw) {
            element.setAttribute(attribute, normalized);
        }
    }

    function normalizeDocument(root = document.body) {
        if (!root) {
            return;
        }

        const walker = document.createTreeWalker(
            root,
            NodeFilter.SHOW_TEXT,
            {
                acceptNode(node) {
                    if (!node.nodeValue || !node.nodeValue.trim()) {
                        return NodeFilter.FILTER_REJECT;
                    }
                    const parent = node.parentElement;
                    if (!parent || ["SCRIPT", "STYLE", "NOSCRIPT", "TEXTAREA"].includes(parent.tagName)) {
                        return NodeFilter.FILTER_REJECT;
                    }
                    return NodeFilter.FILTER_ACCEPT;
                },
            },
        );

        const nodes = [];
        while (walker.nextNode()) {
            nodes.push(walker.currentNode);
        }
        for (const node of nodes) {
            const normalized = humanize(node.nodeValue);
            if (normalized !== node.nodeValue) {
                node.nodeValue = normalized;
            }
        }

        root.querySelectorAll("option").forEach((option) => {
            option.textContent = humanize(option.textContent);
        });
        root.querySelectorAll("optgroup[label]").forEach((element) => normalizeAttribute(element, "label"));
        root.querySelectorAll("[placeholder]").forEach((element) => normalizeAttribute(element, "placeholder"));
        root.querySelectorAll("[title]").forEach((element) => normalizeAttribute(element, "title"));
    }

    global.clinicalPresentation = {
        humanize,
        normalizeDocument,
    };
})(window);
