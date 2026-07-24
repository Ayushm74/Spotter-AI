import React, { useMemo, useState } from "react";
import { createRoot } from "react-dom/client";
import L from "leaflet";
import { CalendarClock, FileText, Fuel, MapPinned, Printer, Route, Truck } from "lucide-react";
import "leaflet/dist/leaflet.css";
import "./styles.css";

const API_URL = import.meta.env.VITE_API_URL ?? "http://127.0.0.1:8000/api";

const statusRows = {
  off: 0,
  sleeper: 1,
  driving: 2,
  on: 3,
};

const statusLabels = {
  off: "Off Duty",
  sleeper: "Sleeper Berth",
  driving: "Driving",
  on: "On Duty",
};

const examples = [
  ["Chicago, IL", "Denver, CO", "Los Angeles, CA", 18],
  ["Atlanta, GA", "Dallas, TX", "Phoenix, AZ", 42],
  ["New York, NY", "Columbus, OH", "Kansas City, MO", 8],
];

function App() {
  const [form, setForm] = useState({
    currentLocation: "Chicago, IL",
    pickupLocation: "Denver, CO",
    dropoffLocation: "Los Angeles, CA",
    currentCycleUsed: 18,
    startAt: new Date().toISOString().slice(0, 16),
  });
  const [plan, setPlan] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  async function submit(event) {
    event.preventDefault();
    setLoading(true);
    setError("");
    try {
      const response = await fetch(`${API_URL}/plan-trip/`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(form),
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || "Unable to plan this trip.");
      setPlan(data);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }

  function update(field, value) {
    setForm((current) => ({ ...current, [field]: value }));
  }

  return (
    <main>
      <section className="planner-shell">
        <aside className="input-panel">
          <div className="brand-row">
            <Truck size={28} />
            <div>
              <h1>Spotter HOS Planner</h1>
              <p>Route planning and FMCSA daily logs for property carriers.</p>
            </div>
          </div>

          <form onSubmit={submit}>
            <Field label="Current location" value={form.currentLocation} onChange={(value) => update("currentLocation", value)} />
            <Field label="Pickup location" value={form.pickupLocation} onChange={(value) => update("pickupLocation", value)} />
            <Field label="Dropoff location" value={form.dropoffLocation} onChange={(value) => update("dropoffLocation", value)} />
            <label className="field">
              <span>Current cycle used (hrs)</span>
              <input
                type="number"
                min="0"
                max="70"
                step="0.25"
                value={form.currentCycleUsed}
                onChange={(event) => update("currentCycleUsed", event.target.value)}
              />
            </label>
            <label className="field">
              <span>Start time</span>
              <input type="datetime-local" value={form.startAt} onChange={(event) => update("startAt", event.target.value)} />
            </label>

            <button className="primary-button" type="submit" disabled={loading}>
              <Route size={18} />
              {loading ? "Planning..." : "Plan trip"}
            </button>
          </form>

          <div className="examples">
            {examples.map(([current, pickup, dropoff, cycle]) => (
              <button key={`${current}-${dropoff}`} onClick={() => setForm({ ...form, currentLocation: current, pickupLocation: pickup, dropoffLocation: dropoff, currentCycleUsed: cycle })}>
                {current.split(",")[0]} to {dropoff.split(",")[0]}
              </button>
            ))}
          </div>

          {error && <p className="error">{error}</p>}
        </aside>

        <section className="results-panel">
          {plan ? <TripResults plan={plan} /> : <EmptyState />}
        </section>
      </section>
    </main>
  );
}

function Field({ label, value, onChange }) {
  return (
    <label className="field">
      <span>{label}</span>
      <input value={value} onChange={(event) => onChange(event.target.value)} />
    </label>
  );
}

function EmptyState() {
  return (
    <div className="empty-state">
      <MapPinned size={46} />
      <h2>Enter trip details to generate a dispatch-ready plan.</h2>
      <p>The output includes the map route, fuel/rest/pickup/dropoff events, and printable log sheets.</p>
    </div>
  );
}

function TripResults({ plan }) {
  return (
    <div className="results-stack">
      <Summary plan={plan} />
      <RouteMap plan={plan} />
      <Stops events={plan.stops} />
      <section className="logs-section">
        <div className="section-heading">
          <div>
            <h2>Daily log sheets</h2>
            <p>{plan.logs.length} sheet{plan.logs.length === 1 ? "" : "s"} generated from duty-status events.</p>
          </div>
          <button className="icon-button" onClick={() => window.print()} title="Print logs">
            <Printer size={18} />
          </button>
        </div>
        {plan.logs.map((log) => (
          <LogSheet key={log.date} log={log} />
        ))}
      </section>
    </div>
  );
}

function Summary({ plan }) {
  const items = [
    ["Route miles", `${plan.route.distanceMiles.toLocaleString()} mi`, MapPinned],
    ["Driving time", `${plan.route.durationDrivingHours} hrs`, CalendarClock],
    ["Elapsed", `${plan.summary.totalElapsedHours} hrs`, Route],
    ["Log sheets", plan.summary.logSheetCount, FileText],
  ];

  return (
    <section className="summary-grid">
      {items.map(([label, value, Icon]) => (
        <div className="metric" key={label}>
          <Icon size={18} />
          <span>{label}</span>
          <strong>{value}</strong>
        </div>
      ))}
    </section>
  );
}

function RouteMap({ plan }) {
  const mapId = useMemo(() => `map-${Math.random().toString(36).slice(2)}`, []);

  React.useEffect(() => {
    const route = plan.route.geometry;
    const map = L.map(mapId, { zoomControl: true, scrollWheelZoom: false });
    L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
      attribution: "&copy; OpenStreetMap",
      maxZoom: 18,
    }).addTo(map);
    const polyline = L.polyline(route, { color: "#2563eb", weight: 5, opacity: 0.85 }).addTo(map);
    const points = [
      ["Current", plan.locations.current],
      ["Pickup", plan.locations.pickup],
      ["Dropoff", plan.locations.dropoff],
    ];
    points.forEach(([label, point]) => L.marker([point.lat, point.lng]).bindPopup(`${label}: ${point.label}`).addTo(map));
    map.fitBounds(polyline.getBounds(), { padding: [28, 28] });
    return () => map.remove();
  }, [mapId, plan]);

  return (
    <section className="map-panel">
      <div className="map-head">
        <h2>Route</h2>
        <span>{plan.route.source === "live" ? "Live OSRM route" : "Estimated route fallback"}</span>
      </div>
      <div id={mapId} className="map" />
    </section>
  );
}

function Stops({ events }) {
  return (
    <section className="stops-panel">
      <div className="section-heading">
        <div>
          <h2>Stops and rests</h2>
          <p>Pickup/dropoff are logged as 1 hour on duty. Fuel stops satisfy the 30-minute break when timed after driving.</p>
        </div>
      </div>
      <div className="timeline">
        {events.map((event, index) => (
          <article className="timeline-item" key={`${event.start}-${index}`}>
            <span className={`dot ${event.status}`} />
            <div>
              <strong>{event.label}</strong>
              <p>{formatRange(event.start, event.end)} · {event.location || "Route segment"} · {statusLabels[event.status]}</p>
            </div>
            {event.label.toLowerCase().includes("fuel") && <Fuel size={18} />}
          </article>
        ))}
      </div>
    </section>
  );
}

function LogSheet({ log }) {
  const width = 920;
  const left = 110;
  const top = 165;
  const gridWidth = 690;
  const rowHeight = 32;
  const hourWidth = gridWidth / 24;

  return (
    <article className="log-sheet">
      <header>
        <div>
          <h3>Drivers Daily Log</h3>
          <span>{new Date(`${log.date}T00:00:00`).toLocaleDateString()}</span>
        </div>
        <div className="log-meta">
          <span>Total miles today</span>
          <strong>{log.miles}</strong>
        </div>
      </header>
      <svg viewBox={`0 0 ${width} 540`} role="img" aria-label={`Daily log for ${log.date}`}>
        <text x="40" y="42" className="svg-title">Drivers Daily Log</text>
        <text x="355" y="35" className="tiny">Original - File at home terminal</text>
        <text x="355" y="52" className="tiny">Duplicate - Driver retains for 8 days</text>
        <FormLine x={40} y={78} w={90} label="Month" value={month(log.date)} />
        <FormLine x={145} y={78} w={90} label="Day" value={day(log.date)} />
        <FormLine x={250} y={78} w={110} label="Year" value={year(log.date)} />
        <FormLine x={40} y={123} w={160} label="Total miles driving today" value={log.miles} />
        <FormLine x={220} y={123} w={200} label="Truck/tractor and trailer numbers" value="SPOTTER-01" />
        <FormLine x={465} y={95} w={315} label="Name of carrier or carriers" value="Spotter AI Demo Carrier" />
        <FormLine x={465} y={132} w={315} label="Main office address" value="Chicago, IL" />

        {[0, 1, 2, 3].map((row) => (
          <React.Fragment key={row}>
            <rect x={left} y={top + row * rowHeight} width={gridWidth} height={rowHeight} className="grid-row" />
            <text x={36} y={top + row * rowHeight + 20} className="row-label">{Object.values(statusLabels)[row]}</text>
          </React.Fragment>
        ))}
        {Array.from({ length: 25 }).map((_, hour) => (
          <g key={hour}>
            <line x1={left + hour * hourWidth} y1={top - 14} x2={left + hour * hourWidth} y2={top + rowHeight * 4} className={hour % 2 === 0 ? "hour-line major" : "hour-line"} />
            {hour < 24 && <text x={left + hour * hourWidth + 2} y={top - 20} className="hour-label">{hour === 0 ? "Mid" : hour === 12 ? "Noon" : hour}</text>}
          </g>
        ))}
        {Array.from({ length: 24 * 4 + 1 }).map((_, tick) => (
          <line key={tick} x1={left + tick * (hourWidth / 4)} y1={top} x2={left + tick * (hourWidth / 4)} y2={top + rowHeight * 4} className="quarter-line" />
        ))}
        {log.events.map((event, index) => {
          const y = top + statusRows[event.status] * rowHeight + rowHeight / 2;
          const x1 = left + event.startHour * hourWidth;
          const x2 = left + event.endHour * hourWidth;
          return <line key={`${event.start}-${index}`} x1={x1} y1={y} x2={x2} y2={y} className={`duty-line ${event.status}`} />;
        })}
        {log.events.slice(0, 8).map((event, index) => (
          <text key={`${event.label}-${index}`} x={left + 8 + index * 82} y={342 + (index % 2) * 18} className="remark">{event.location || event.label}</text>
        ))}
        <text x={36} y={334} className="remarks-label">Remarks</text>
        <line x1={36} y1={348} x2={842} y2={348} className="remark-line" />
        <line x1={36} y1={372} x2={842} y2={372} className="remark-line" />
        <line x1={36} y1={396} x2={842} y2={396} className="remark-line" />
        {Object.entries(log.totals).map(([key, value], index) => (
          <g key={key}>
            <text x={825} y={top + index * rowHeight + 20} className="total-hours">{value}</text>
          </g>
        ))}
        <text x={818} y={top - 20} className="tiny">Total Hours</text>
        <text x={770} y={430} className="total-check">= 24</text>
      </svg>
    </article>
  );
}

function FormLine({ x, y, w, label, value }) {
  return (
    <g>
      <text x={x} y={y - 11} className="tiny">{label}</text>
      <line x1={x} y1={y} x2={x + w} y2={y} className="form-line" />
      <text x={x + 4} y={y - 4} className="form-value">{value}</text>
    </g>
  );
}

function formatRange(start, end) {
  return `${new Date(start).toLocaleString([], { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" })} - ${new Date(end).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" })}`;
}

function month(value) {
  return String(new Date(`${value}T00:00:00`).getMonth() + 1).padStart(2, "0");
}

function day(value) {
  return String(new Date(`${value}T00:00:00`).getDate()).padStart(2, "0");
}

function year(value) {
  return new Date(`${value}T00:00:00`).getFullYear();
}

createRoot(document.getElementById("root")).render(<App />);
