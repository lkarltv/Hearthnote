const radians = Math.PI / 180;
const dayMs = 86_400_000;
const sunriseZenith = Math.cos(90.833 * radians);

export function isDaylight(date, location) {
  if (!location) return date.getHours() >= 7 && date.getHours() < 19;

  // NOAA solar position equations, evaluated in UTC so DST has no effect.
  // https://gml.noaa.gov/grad/solcalc/solareqns.PDF
  const year = date.getUTCFullYear();
  const yearStart = Date.UTC(year, 0, 1);
  const yearLength = (Date.UTC(year + 1, 0, 1) - yearStart) / dayMs;
  const angle = 2 * Math.PI / yearLength * ((date.getTime() - yearStart) / dayMs - 0.5);
  const cos1 = Math.cos(angle), sin1 = Math.sin(angle);
  const cos2 = Math.cos(2 * angle), sin2 = Math.sin(2 * angle);
  const equationOfTime = 229.18 * (
    0.000075 + 0.001868 * cos1 - 0.032077 * sin1 - 0.014615 * cos2 - 0.040849 * sin2
  );
  const declination = 0.006918 - 0.399912 * cos1 + 0.070257 * sin1
    - 0.006758 * cos2 + 0.000907 * sin2
    - 0.002697 * Math.cos(3 * angle) + 0.00148 * Math.sin(3 * angle);
  const utcMinutes = date.getUTCHours() * 60 + date.getUTCMinutes() + date.getUTCSeconds() / 60;
  const hourAngle = ((utcMinutes + equationOfTime + 4 * location.longitude) / 4 - 180) * radians;
  const latitude = location.latitude * radians;
  const zenith = Math.sin(latitude) * Math.sin(declination)
    + Math.cos(latitude) * Math.cos(declination) * Math.cos(hourAngle);
  return zenith >= sunriseZenith;
}
