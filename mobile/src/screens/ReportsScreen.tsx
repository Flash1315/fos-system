import React, { useEffect, useRef, useState } from "react";
import { Alert, Share, Text, StyleSheet, View } from "react-native";
import { downloadReportCsv, onResumeRefresh, orgReport, type OrgReport, type ReportPeriod } from "../api";
import { alertFosError } from "../alertError";
import { Btn, Card, Chip, Field, Label, Screen, Sub, TopBar } from "../components/ui";
import { isValidYmd } from "../dates";
import { colors } from "../theme";

const PERIODS: { label: string; days?: number }[] = [
  { label: "365d", days: 365 },
  { label: "7d", days: 7 },
  { label: "30d", days: 30 },
  { label: "90d", days: 90 },
];

export function ReportsScreen({ onBack }: { onBack: () => void }) {
  const [report, setReport] = useState<OrgReport | null>(null);
  const [days, setDays] = useState<number | undefined>(365);
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");
  const [dateFromDebounced, setDateFromDebounced] = useState("");
  const [dateToDebounced, setDateToDebounced] = useState("");
  const [custom, setCustom] = useState(false);
  const [exporting, setExporting] = useState(false);
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
      const next = await orgReport(period());
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

  const onExport = async () => {
    if (custom) {
      const from = dateFromDebounced;
      const to = dateToDebounced;
      if (!from && !to) {
        Alert.alert("Fos", "Enter from and/or to date before export");
        return;
      }
      if (from && !isValidYmd(from)) {
        Alert.alert("Fos", "From date must be a real calendar day (YYYY-MM-DD)");
        return;
      }
      if (to && !isValidYmd(to)) {
        Alert.alert("Fos", "To date must be a real calendar day (YYYY-MM-DD)");
        return;
      }
      if (from && to && from > to) {
        Alert.alert("Fos", "From date must be on or before to date");
        return;
      }
    }
    if (loadError && !report) {
      Alert.alert("Fos", "Fix the period error before export");
      return;
    }
    setExporting(true);
    try {
      const text = await downloadReportCsv(period());
      if (typeof document !== "undefined") {
        const blob = new Blob([text], { type: "text/csv" });
        const url = URL.createObjectURL(blob);
        const a = document.createElement("a");
        a.href = url;
        a.download = "fos-export.csv";
        a.click();
        URL.revokeObjectURL(url);
        Alert.alert("Fos", "CSV downloaded");
      } else {
        const MAX_SHARE_CHARS = 80_000;
        if (text.length > MAX_SHARE_CHARS) {
          Alert.alert(
            "Fos",
            `Export is ~${Math.round(text.length / 1024)} KB — too large to share here. Narrow the date range or download from web.`,
          );
          return;
        }
        const rows = Math.max(0, text.split("\n").length - 1);
        await Share.share({
          message: text,
          title: `fos-export.csv (${rows} rows)`,
        });
      }
    } catch (e) {
      alertFosError(e, "Export failed");
    } finally {
      setExporting(false);
    }
  };

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
          <Label>Net result (period)</Label>
          <Text style={styles.big}>
            {(report.net_result ?? report.cash_position).toLocaleString()} {report.currency}
          </Text>
          <Sub>All income - all approved spend</Sub>
          <Label>Cash movement (period)</Label>
          <Text style={styles.line}>
            {report.cash_position.toLocaleString()} {report.currency}
          </Text>
          <Sub>Cash income - spend paid from cash on hand</Sub>
          <Sub>
            {report.pending_count} pending · {report.team_count} active teammates
          </Sub>
          <Label>Spend from cash / my pocket</Label>
          <Text style={styles.line}>
            {(report.spend_from_cash ?? 0).toLocaleString()} /{" "}
            {(report.spend_from_pocket ?? 0).toLocaleString()}
          </Text>
          {(report.internal_transfer_total ?? 0) > 0 && (
            <>
              <Label>Internal transfers (excluded from totals)</Label>
              <Text style={styles.line}>{(report.internal_transfer_total ?? 0).toLocaleString()}</Text>
            </>
          )}
          <Label>Team held cash</Label>
          <Text style={styles.line}>{(report.total_cash_held ?? 0).toLocaleString()}</Text>
          <Label>Team spendings owed</Label>
          <Text style={styles.line}>{(report.total_spendings ?? 0).toLocaleString()}</Text>
        </Card>
        <Card>
          <Label>Approved totals</Label>
          <Text style={styles.line}>Expense: {report.approved_expense_total.toLocaleString()}</Text>
          <Text style={styles.line}>Fuel: {report.approved_fuel_total.toLocaleString()}</Text>
          <Text style={styles.line}>Income cash: {report.approved_income_cash.toLocaleString()}</Text>
          <Text style={styles.line}>
            Income transfer: {report.approved_income_transfer.toLocaleString()}
          </Text>
        </Card>
        <Card>
          <Label>By category</Label>
          {report.by_category.length === 0 ? (
            <Sub>No approved records yet</Sub>
          ) : (
            report.by_category.map((c) => (
              <Text key={`${c.kind}-${c.category}`} style={styles.line}>
                {c.kind}/{c.category}: {c.total.toLocaleString()}
              </Text>
            ))
          )}
        </Card>
        <Card>
          <Label>By purpose (spend)</Label>
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
        <Btn title={exporting ? "…" : "Export CSV"} onPress={onExport} disabled={exporting} />
      </>
    );
  }

  return (
    <Screen scroll refreshing={refreshingPeriod} onRefresh={() => void reload()}>
      <TopBar onBack={onBack} onCancel={onBack} />
      <Label>Org reports</Label>
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
        <View style={styles.kinds}>
          <Field
            style={{ flex: 1 }}
            value={dateFrom}
            onChangeText={setDateFrom}
            placeholder="From YYYY-MM-DD"
            autoCapitalize="none"
            maxLength={10}
          />
          <Field
            style={{ flex: 1 }}
            value={dateTo}
            onChangeText={setDateTo}
            placeholder="To YYYY-MM-DD"
            autoCapitalize="none"
            maxLength={10}
          />
        </View>
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
  kinds: { flexDirection: "row", gap: 8, marginBottom: 8, flexWrap: "wrap" },
  big: { color: colors.text, fontSize: 28, fontWeight: "700", marginBottom: 4 },
  line: { color: colors.text, marginBottom: 4 },
});
