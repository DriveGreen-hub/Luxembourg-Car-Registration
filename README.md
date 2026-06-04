# Luxembourg Car Registration

An interactive dashboard for **new vehicle registrations in Luxembourg**, built
on the open [Parc Automobile du Luxembourg][src] dataset (Société Nationale de
Circulation Automobile — SNCA), licence CC0.

**Live:** https://drivegreen-hub.github.io/Luxembourg-Car-Registration/

## What it shows

- Periods — focus month, year-to-date, rolling 12 months, full history, with
  month-on-month and year-on-year deltas.
- Segments — passenger cars, vans, buses, and heavy trucks (HDV).
- Type — brand-new vs used import.
- Breakdowns — by manufacturer, model and drivetrain
  (BEV / PHEV / HEV / Petrol / Diesel / Other), with type-to-search on brand and model.
- BEV adoption over time, registration-weighted CO₂ intensity, and CSV / PNG export.

## Method, in brief

The published dataset is a monthly **stock snapshot** of every registered
vehicle, not a feed of registrations. The figures here are reconstructed from
each vehicle's registration dates and EU vehicle category, then bucketed by the
month of first Luxembourg registration. Recent months use the official
operation code to split new vs import; older snapshots, which omit it, fall back
to a date comparison. Counts for months far in the past are subject to mild
survivorship bias (vehicles since exported or scrapped), so they are best read
as close estimates rather than exact official figures.

Data: Parc Automobile du Luxembourg (SNCA), via data.public.lu, licence CC0.

[src]: https://data.public.lu/fr/datasets/parc-automobile-du-luxembourg/
