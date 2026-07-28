import React, { useEffect, useRef, useState } from "react";
import { Alert, Text, StyleSheet, View } from "react-native";
import { myReport, onResumeRefresh, type MyReport, type ReportPeriod } from "../api";
import { Btn, Card, Chip, Field, Label, Screen, Sub, TopBar } from "../components/ui";
import { isValidYmd } from "../dates";
import { colors } from "../theme";

const PERIODS: { label: string; days?: number }[] = [
  { label: "365d", days: 365 },
  { label: "7d", days: 7 },
  { label: "30d", days: 30 },
  { label: "90d", days: 90 },
];

export function MyReportScreen({ onBack }: { onBack: () => void }) {
  const [report, setReport] = useState<MyReport | null>(null);
  const [days, setDays] = useState<number | undefined>(365);
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");
  const [dateFromDebounced, setDateFromDebounced] = useState("");
  const [dateToDebounced, setDateToDebounced] = useState("");
  const [custom, setCustom] = useState(false);
  const [loadError, setLoadError] = useState("");
  const [refreshingPeriod, setRefreshingPeriod] = useState(false);
  const reloadGen = useRef(0);

  useEffect(() => {
    const t = setTimeout(() => setDateFromDebounced(dateFrom.trim()), 400);
    return () => clearTimeout(t);
  }, [dateFrom]);
  useEffect(() => {
    const t = setTimeout(() => setDateToDebounced(dateTo.trim()), 400);
    return () => clearTimeout(t);
  }, [dateTo]);

  const period = (): ReportPeriod | undefined => {
    if (custom && (dateFromDebounced || dateToDebounced)) {
      return {
        date_from: dateFromDebounced || undefined,
        date_to: dateToDebounced || undefined,
      };
    }
    return days != null ? { days } : undefined;
  };

  const reload = async () => {
    const gen = ++reloadGen.current;
    try {
      if (custom) {
        const from = dateFromDebounced;
        const to = dateToDebounced;
        if (!from && !to) {
          if (gen !== reloadGen.current) return;
          setLoadError("Enter from and/or to date (YYYY-MM-DD)");
          return;
        }
        if (from && !isValidYmd(from)) {
          if (gen !== reloadGen.current) return;
          setLoadError("From date must be a real calendar day (YYYY-MM-DD)");
          return;
        }
        if (to && !isValidYmd(to)) {
          if (gen !== reloadGen.current) return;
          setLoadError("To date must be a real calendar day (YYYY-MM-DD)");
          return;
        }
        if (from && to && from > to) {
          if (gen !== reloadGen.current) return;
          setLoadError("From date must be on or before to date");
          return;
        }
      }
      if (gen !== reloadGen.current) return;
      setLoadError("");
      setRefreshingPeriod(true);
      const next = await myReport(period());
      if (gen !== reloadGen.current) return;
      setReport(next);
    } catch (e) {
      if (gen !== reloadGen.current) return;
      setLoadError(e instanceof Error ? e.message : "Failed");
    } finally {
      if (gen === reloadGen.current) setRefreshingPeriod(false);
    }
  };

  useEffect(() => {
    void reload();
  }, [days, custom, dateFromDebounced, dateToDebounced]);

  useEffect(() => onResumeRefresh(() => {
    void reload();
  }), []);

  let body: React.ReactNode = null;
  if (!report && !loadError) {
    body = <Sub>Loading...</Sub>;
  } else if (loadError && !report) {
    body = (
      <>
        <Sub>Could not load — {loadError}</Sub>
        <Btn title="Retry" variant="ghost" onPress={reload} />
      </>
    );
  } else if (report) {
    body = (
      <>
        {!!loadError && (
          <>
            <Sub>Refresh failed — {loadError}</Sub>
            <Btn title="Retry" variant="ghost" onPress={reload} />
          </>
        )}
        {refreshingPeriod && <Sub>Updating for selected period…</Sub>}
        <Card>
          <Label>Cash on hand</Label>
          <Text style={styles.big}>
            {report.cash_on_hand.toLocaleString()} {report.currency}
          </Text>
          <Label>Spendings owed</Label>
          <Text style={styles.line}>{report.spendings.toLocaleString()}</Text>
          <Sub>{report.pending_count} pending</Sub>
        </Card>
        <Card>
          <Label>Approved totals</Label>
          <Text style={styles.line}>Expense: {report.approved_expense_total.toLocaleString()}</Text>
          <Text style={styles.line}>Fuel: {report.approved_fuel_total.toLocaleString()}</Text>
          <Text style={styles.line}>Income cash: {report.approved_income_cash.toLocaleString()}</Text>
        </Card>
        <Card>
          <Label>By purpose</Label>
          {(report.by_purpose ?? []).length === 0 ? (
            <Sub>No approved spend yet</Sub>
          ) : (
            (report.by_purpose ?? []).map((p) => (
              <Text key={p.purpose} style={styles.line}>
                {p.purpose}: {p.total.toLocaleString()}
              </Text>
            ))
          )}
        </Card>
        <Card>
          <Label>By category</Label>
          {(report.by_category ?? []).length === 0 ? (
            <Sub>No approved records yet</Sub>
          ) : (
            (report.by_category ?? []).map((c) => (
              <Text key={`${c.kind}-${c.category}`} style={styles.line}>
                {c.kind}/{c.category}: {c.total.toLocaleString()}
              </Text>
            ))
          )}
        </Card>
      </>
    );
  }

  return (
    <Screen scroll refreshing={refreshingPeriod} onRefresh={() => void reload()}>
      <TopBar onBack={onBack} onCancel={onBack} />
      <Text style={styles.title}>My stats</Text>
      <View style={styles.kinds}>
        {PERIODS.map((p) => (
          <Chip
            key={p.label}
            label={p.label}
            on={!custom && days === p.days}
            onPress={() => {
              setCustom(false);
              setDays(p.days);
            }}
          />
        ))}
        <Chip
          label="custom"
          on={custom}
          onPress={() => {
            setCustom(true);
            setDays(undefined);
          }}
        />
      </View>
      {custom && (
        <>
          <Label>From (YYYY-MM-DD)</Label>
          <Field autoCapitalize="none" value={dateFrom} onChangeText={setDateFrom} placeholder="optional" maxLength={10} />
          <Label>To (YYYY-MM-DD)</Label>
          <Field autoCapitalize="none" value={dateTo} onChangeText={setDateTo} placeholder="optional" maxLength={10} />
        </>
      )}
      {(custom || days != null) && (
        <Btn
          title="Clear filters"
          variant="ghost"
          onPress={() => {
            setCustom(false);
            setDays(undefined);
            setDateFrom("");
            setDateTo("");
          }}
        />
      )}
      {body}
    </Screen>
  );
}

const styles = StyleSheet.create({
  title: { color: colors.text, fontSize: 26, fontWeight: "700", marginVertical: 8 },
  big: { color: colors.text, fontSize: 24, fontWeight: "700" },
  line: { color: colors.text, marginTop: 6 },
  kinds: { flexDirection: "row", gap: 8, marginBottom: 8, flexWrap: "wrap" },
});
