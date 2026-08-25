const express = require("express");
const cors = require("cors");
const schemes = require("./data/schemes.json");
const partners = require("./data/partners.json");

const app = express();
app.use(cors());
app.use(express.json());

// ---------- helpers ----------

function haversineKm(lat1, lng1, lat2, lng2) {
  const toRad = (d) => (d * Math.PI) / 180;
  const R = 6371;
  const dLat = toRad(lat2 - lat1);
  const dLng = toRad(lng2 - lng1);
  const a =
    Math.sin(dLat / 2) ** 2 +
    Math.cos(toRad(lat1)) * Math.cos(toRad(lat2)) * Math.sin(dLng / 2) ** 2;
  return R * 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a));
}

// Reducing-balance EMI, with a moratorium period during which
// only interest accrues (no principal repayment).
function calculateEMI({ principal, annualRate, tenureMonths, moratoriumMonths = 0 }) {
  const monthlyRate = annualRate / 12 / 100;
  const repaymentMonths = tenureMonths - moratoriumMonths;

  if (repaymentMonths <= 0) {
    throw new Error("Moratorium period cannot be >= total tenure");
  }

  // Interest that accrues during moratorium gets added to principal
  // (capitalized) once EMI repayment starts.
  const capitalizedPrincipal =
    principal * (1 + monthlyRate) ** moratoriumMonths;

  const emi =
    monthlyRate === 0
      ? capitalizedPrincipal / repaymentMonths
      : (capitalizedPrincipal * monthlyRate * (1 + monthlyRate) ** repaymentMonths) /
        ((1 + monthlyRate) ** repaymentMonths - 1);

  const totalPayment = emi * repaymentMonths;
  const totalInterest = totalPayment - principal;

  return {
    emi: Math.round(emi),
    repaymentMonths,
    moratoriumMonths,
    totalPayment: Math.round(totalPayment),
    totalInterest: Math.round(totalInterest),
    capitalizedPrincipal: Math.round(capitalizedPrincipal),
  };
}

// ---------- routes ----------

// POST /api/recommend
// body: { projectType: "business" | "education", cost, income }
app.post("/api/recommend", (req, res) => {
  const { projectType, cost, income } = req.body;

  if (cost == null || income == null || !projectType) {
    return res.status(400).json({ error: "projectType, cost, and income are required" });
  }

  const reasoning = [];

  const incomeEligible = income <= 500000;
  reasoning.push(
    incomeEligible
      ? `Your annual family income of ₹${Number(income).toLocaleString("en-IN")} is within the ₹5,00,000 eligibility cap.`
      : `Your annual family income of ₹${Number(income).toLocaleString("en-IN")} exceeds the ₹5,00,000 eligibility cap.`
  );

  if (!incomeEligible) {
    return res.json({ eligible: false, scheme: null, reasoning });
  }

  const candidates = schemes.filter((s) => {
    const typeMatches =
      projectType === "education" ? s.type === "education" : s.type === "project";
    return typeMatches && cost >= s.minCost && cost <= s.maxCost;
  });

  if (candidates.length === 0) {
    reasoning.push(
      `No scheme currently covers a ${projectType} cost of ₹${Number(cost).toLocaleString("en-IN")} — it falls outside all defined slabs.`
    );
    return res.json({ eligible: false, scheme: null, reasoning });
  }

  const scheme = candidates[0];
  reasoning.push(
    `Your ${projectType} cost of ₹${Number(cost).toLocaleString("en-IN")} falls under the ${scheme.name} range (₹${scheme.minCost.toLocaleString("en-IN")}–₹${scheme.maxCost.toLocaleString("en-IN")}).`
  );
  reasoning.push(
    `This scheme covers up to ${scheme.coveragePercent}% of cost at ${scheme.interestRate}% p.a., with a ${scheme.moratoriumMonths}-month moratorium.`
  );

  res.json({ eligible: true, scheme, reasoning });
});

// POST /api/calculate
// body: { principal, annualRate, tenureMonths, moratoriumMonths }
app.post("/api/calculate", (req, res) => {
  const { principal, annualRate, tenureMonths, moratoriumMonths } = req.body;

  if (principal == null || annualRate == null || tenureMonths == null) {
    return res.status(400).json({ error: "principal, annualRate, and tenureMonths are required" });
  }

  try {
    const result = calculateEMI({
      principal: Number(principal),
      annualRate: Number(annualRate),
      tenureMonths: Number(tenureMonths),
      moratoriumMonths: Number(moratoriumMonths) || 0,
    });
    res.json(result);
  } catch (err) {
    res.status(400).json({ error: err.message });
  }
});

// GET /api/partners?lat=..&lng=..&schemeId=..
app.get("/api/partners", (req, res) => {
  const lat = parseFloat(req.query.lat);
  const lng = parseFloat(req.query.lng);
  const schemeId = req.query.schemeId;

  if (isNaN(lat) || isNaN(lng)) {
    return res.status(400).json({ error: "lat and lng query params are required" });
  }

  let results = partners
    .filter((p) => !p.highNPA) // exclude partners with high NPA/overdue flag
    .filter((p) => !schemeId || p.schemesHandled.includes(schemeId))
    .map((p) => ({
      ...p,
      distanceKm: Math.round(haversineKm(lat, lng, p.lat, p.lng) * 10) / 10,
    }))
    .sort((a, b) => a.distanceKm - b.distanceKm);

  res.json({ count: results.length, partners: results });
});

app.get("/api/schemes", (req, res) => res.json(schemes));

const PORT = process.env.PORT || 4000;
app.listen(PORT, () => console.log(`Backend running on http://localhost:${PORT}`));
