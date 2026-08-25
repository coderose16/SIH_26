const API_BASE = "http://localhost:4000/api";

let recommendedSchemeId = null;
let map, markerLayer;

// ---------- 1. Recommender ----------

document.getElementById("recommendForm").addEventListener("submit", async (e) => {
  e.preventDefault();
  const projectType = document.getElementById("projectType").value;
  const cost = Number(document.getElementById("cost").value);
  const income = Number(document.getElementById("income").value);

  const res = await fetch(`${API_BASE}/recommend`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ projectType, cost, income }),
  });
  const data = await res.json();

  const box = document.getElementById("recommendResult");
  box.classList.remove("hidden");

  if (!data.eligible) {
    box.innerHTML = `
      <div class="bg-red-50 border border-red-200 rounded-lg p-4">
        <p class="font-medium text-red-700">Not eligible for a listed scheme</p>
        <ul class="list-disc list-inside text-sm text-red-600 mt-2">
          ${data.reasoning.map((r) => `<li>${r}</li>`).join("")}
        </ul>
      </div>`;
    return;
  }

  recommendedSchemeId = data.scheme.id;

  box.innerHTML = `
    <div class="bg-green-50 border border-green-200 rounded-lg p-4">
      <p class="font-semibold text-green-800 text-lg">${data.scheme.name}</p>
      <p class="text-sm text-green-700 mb-2">${data.scheme.description}</p>
      <ul class="list-disc list-inside text-sm text-gray-700 space-y-1">
        ${data.reasoning.map((r) => `<li>${r}</li>`).join("")}
      </ul>
    </div>`;

  // Prefill the EMI calculator with this scheme's numbers
  document.getElementById("principal").value = Math.round(cost * (data.scheme.coveragePercent / 100));
  document.getElementById("rate").value = data.scheme.interestRate;
  document.getElementById("moratorium").value = data.scheme.moratoriumMonths;
});

// ---------- 2. EMI Calculator ----------

document.getElementById("calcForm").addEventListener("submit", async (e) => {
  e.preventDefault();
  const principal = Number(document.getElementById("principal").value);
  const annualRate = Number(document.getElementById("rate").value);
  const tenureMonths = Number(document.getElementById("tenure").value);
  const moratoriumMonths = Number(document.getElementById("moratorium").value);

  const res = await fetch(`${API_BASE}/calculate`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ principal, annualRate, tenureMonths, moratoriumMonths }),
  });
  const data = await res.json();

  const box = document.getElementById("calcResult");
  box.classList.remove("hidden");

  if (data.error) {
    box.innerHTML = `<div class="bg-red-50 border border-red-200 rounded-lg p-4 text-red-700">${data.error}</div>`;
    return;
  }

  box.innerHTML = `
    <div class="bg-indigo-50 border border-indigo-200 rounded-lg p-4 grid grid-cols-2 gap-3 text-sm">
      <div><span class="text-gray-500">Monthly EMI</span><p class="text-xl font-bold text-indigo-700">₹${data.emi.toLocaleString("en-IN")}</p></div>
      <div><span class="text-gray-500">Repayment months</span><p class="font-semibold">${data.repaymentMonths}</p></div>
      <div><span class="text-gray-500">Total interest</span><p class="font-semibold">₹${data.totalInterest.toLocaleString("en-IN")}</p></div>
      <div><span class="text-gray-500">Total payment</span><p class="font-semibold">₹${data.totalPayment.toLocaleString("en-IN")}</p></div>
    </div>`;
});

// ---------- 3. Partner Locator ----------

document.getElementById("locateBtn").addEventListener("click", () => {
  if (!navigator.geolocation) {
    alert("Geolocation not supported by this browser.");
    return;
  }
  navigator.geolocation.getCurrentPosition(async (pos) => {
    const { latitude, longitude } = pos.coords;
    const schemeParam = recommendedSchemeId ? `&schemeId=${recommendedSchemeId}` : "";
    const res = await fetch(`${API_BASE}/partners?lat=${latitude}&lng=${longitude}${schemeParam}`);
    const data = await res.json();
    renderPartners(data.partners, latitude, longitude);
  }, () => {
    alert("Could not get your location — check browser permissions.");
  });
});

function renderPartners(partners, userLat, userLng) {
  const mapEl = document.getElementById("map");
  mapEl.classList.remove("hidden");

  if (!map) {
    map = L.map("map").setView([userLat, userLng], 12);
    L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png").addTo(map);
    markerLayer = L.layerGroup().addTo(map);
  } else {
    map.setView([userLat, userLng], 12);
  }
  markerLayer.clearLayers();

  L.marker([userLat, userLng]).addTo(markerLayer).bindPopup("You are here").openPopup();

  const list = document.getElementById("partnerList");
  list.innerHTML = "";

  if (partners.length === 0) {
    list.innerHTML = `<li class="text-sm text-gray-500">No eligible partner found nearby for this scheme.</li>`;
    return;
  }

  partners.forEach((p) => {
    L.marker([p.lat, p.lng]).addTo(markerLayer).bindPopup(`${p.name} (${p.distanceKm} km)`);

    const li = document.createElement("li");
    li.className = "border rounded-lg p-3 flex justify-between items-center text-sm";
    li.innerHTML = `
      <div>
        <p class="font-medium">${p.name}</p>
        <p class="text-gray-500">${p.type} · handles: ${p.schemesHandled.join(", ")}</p>
      </div>
      <span class="text-indigo-700 font-semibold">${p.distanceKm} km</span>`;
    list.appendChild(li);
  });
}

// ---------- Voice input (Web Speech API) ----------

document.getElementById("micBtn").addEventListener("click", () => {
  const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
  if (!SpeechRecognition) {
    alert("Voice input isn't supported in this browser — try Chrome.");
    return;
  }
  const recognition = new SpeechRecognition();
  recognition.lang = "en-IN"; // swap to hi-IN, kn-IN etc. for regional language input
  recognition.interimResults = false;

  recognition.onresult = (event) => {
    const transcript = event.results[0][0].transcript;
    parseSpokenDetails(transcript);
  };
  recognition.onerror = () => alert("Didn't catch that — please try again.");

  recognition.start();
});

// Very simple keyword + number extraction: e.g.
// "cost is 8 lakh income is 3 lakh for business"
function parseSpokenDetails(text) {
  const lower = text.toLowerCase();

  const numberNear = (keyword) => {
    const regex = new RegExp(`${keyword}[^0-9]{0,15}([0-9,.]+)\\s*(lakh|lac|thousand)?`, "i");
    const match = lower.match(regex);
    if (!match) return null;
    let value = parseFloat(match[1].replace(/,/g, ""));
    if (match[2] && match[2].startsWith("lakh")) value *= 100000;
    if (match[2] === "thousand") value *= 1000;
    return Math.round(value);
  };

  const cost = numberNear("cost");
  const income = numberNear("income");

  if (cost) document.getElementById("cost").value = cost;
  if (income) document.getElementById("income").value = income;
  if (lower.includes("education") || lower.includes("study")) {
    document.getElementById("projectType").value = "education";
  } else if (lower.includes("business") || lower.includes("project")) {
    document.getElementById("projectType").value = "business";
  }

  alert(`Heard: "${text}"\nFilled in what I could recognize — please check the fields.`);
}
