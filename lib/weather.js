// Weather from Open-Meteo (free, no key) for the board's today screen and the voice assistant.
const WMO = {
  0: 'Clear', 1: 'Mostly clear', 2: 'Partly cloudy', 3: 'Cloudy', 45: 'Fog', 48: 'Freezing fog',
  51: 'Light drizzle', 53: 'Drizzle', 55: 'Heavy drizzle', 56: 'Freezing drizzle', 57: 'Freezing drizzle',
  61: 'Light rain', 63: 'Rain', 65: 'Heavy rain', 66: 'Freezing rain', 67: 'Freezing rain',
  71: 'Light snow', 73: 'Snow', 75: 'Heavy snow', 77: 'Snow grains',
  80: 'Showers', 81: 'Heavy showers', 82: 'Violent showers', 85: 'Snow showers', 86: 'Snow showers',
  95: 'Thunderstorm', 96: 'Thunderstorm, hail', 99: 'Thunderstorm, hail',
};

export async function getWeather(lat, lon) {
  const q = new URLSearchParams({
    latitude: lat.toFixed(4),
    longitude: lon.toFixed(4),
    current: 'temperature_2m,relative_humidity_2m,apparent_temperature,weather_code,wind_speed_10m,precipitation,is_day',
    minutely_15: 'precipitation',
    forecast_minutely_15: '5',
    daily: 'temperature_2m_max,temperature_2m_min,precipitation_probability_max,weather_code',
    timezone: 'auto',
    wind_speed_unit: 'kmh',
    forecast_days: '2',
  });
  const res = await fetch(`https://api.open-meteo.com/v1/forecast?${q}`, { signal: AbortSignal.timeout(6000) });
  if (!res.ok) throw new Error(`open-meteo ${res.status}`);
  const { current: c, daily: d, minutely_15: m } = await res.json();
  const day = (i) => ({
    condition: WMO[d.weather_code[i]] ?? 'Unknown',
    high_c: Math.round(d.temperature_2m_max[i]),
    low_c: Math.round(d.temperature_2m_min[i]),
    rain_chance: d.precipitation_probability_max[i],
  });
  return {
    temp_c: Math.round(c.temperature_2m),
    feels_c: Math.round(c.apparent_temperature),
    humidity: c.relative_humidity_2m,
    wind_kmh: Math.round(c.wind_speed_10m),
    condition: WMO[c.weather_code] ?? 'Unknown',
    is_day: c.is_day !== 0, // the board's today screen draws a moon at night
    today: day(0),
    tomorrow: day(1),
    rain_soon: rainSoon(c, m),
  };
}

// Dry now but rain in the next hour: the local time it should start ("14:30"), else null. The board
// says so once (companion.py).
function rainSoon(c, m) {
  if (!m || c.precipitation >= 0.1) return null;
  for (let i = 0; i < m.time.length; i++) {
    if (m.time[i] > c.time && m.precipitation[i] >= 0.2) return m.time[i].slice(11, 16);
  }
  return null;
}
