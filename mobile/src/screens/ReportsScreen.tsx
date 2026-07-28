import React, { useState } from "react";
import { Alert, Text, StyleSheet, View } from "react-native";
import { useFocusEffect } from "../useFocus";
import { exportReportCsv, getToken, orgReport, type OrgReport, type ReportPeriod } from "../api";
import { Btn, Card, Chip, Field, Label, Screen, Sub, TopBar } from "../components/ui";
import { colors } from "../theme";

const PERIODS: { label: string; days?: number }[] = [
  { label: "all" },
  { label: "7d", days: 7 },
  { label: "30d", days: 30 },
  { label: "90d", days: 90 },
];

export function ReportsScreen({ onBack }: { onBack: () => void }) {
  const [report, setReport] = useState<OrgReport | null>(null);
  const [days, setDays] = useState<number | undefined>(undefined);
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");
  const [custom, setCustom] = useState(false);
  const [exporting, setExporting] = useState(false);

  const period = (): ReportPeriod | undefined => {
    if (custom && (dateFrom.trim() || dateTo.trim())) {
      return { date_from: dateFrom.trim() || undefined, date_to: dateTo.trim() || undefined };
    }
    return days != null ? { days } : undefined;
  };

  const reload = async () => {
    try {
      setReport(await orgReport(period()));
    } catch (e) {
      Alert.alert("Fos", e instanceof Error ? e.message : "Failed");
    }
  };

  useFocusEffect(reload);
  React.useEffect(() => {
    void reload();
  }, [days, custom, dateFrom, dateTo]);

  const onExport = async () => {
    setExporting(true);
    try {
      const token = await getToken();
      const res = await fetch(exportReportCsv(period()), {
        headers: token ? { Authorization: `Bearer ${token}` } : {},
      });
      if (!res.ok) throw new Error(`Export failed (${res.status})`);
      const text = await res.text();
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
        Alert.alert("Fos", `Exported ${Math.max(0, text.split("\n").length - 1)} rows`);
      }
    } catch (e) {
      Alert.alert("Fos", e instanceof Error ? e.message : "Export failed");
    } finally {
      setExporting(false);
    }
  };

  return (
    <Screen scroll>
      <TopBar onBack={onBack} onCancel={onBack} />
      <Text style={styles.title}>Org report</Text>
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
          <Field autoCapitalize="none" value={dateFrom} onChangeText={setDateFrom} placeholder="optional" />
          <Label>To (YYYY-MM-DD)</Label>
          <Field autoCapitalize="none" value={dateTo} onChangeText={setDateTo} placeholder="optional" />
        </>
      )}
      <Btn title={exporting ? "…" : "Export CSV"} variant="ghost" onPress={onExport} disabled={exporting} />
      {!report ? (
        <Sub>Loading…</Sub>
      ) : (
        <>
          <Card>
            <Label>Net result (period)</Label>
            <Text style={styles.big}>
              {(report.net_result ?? report.cash_position).toLocaleString()} {report.currency}
            </Text>
            <Sub>All income − all approved spend</Sub>
            <Label>Cash movement (period)</Label>
            <Text style={styles.line}>
              {report.cash_position.toLocaleString()} {report.currency}
            </Text>
            <Sub>Cash income − spend paid from cash on hand</Sub>
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
        </>
      )}
    </Screen>
  );
}

const styles = StyleSheet.create({
  title: { color: colors.text, fontSize: 26, fontWeight: "700", marginVertical: 8 },
  big: { color: colors.text, fontSize: 24, fontWeight: "700" },
  line: { color: colors.text, marginTop: 6 },
  kinds: { flexDirection: "row", gap: 8, marginBottom: 8, flexWrap: "wrap" },
});
