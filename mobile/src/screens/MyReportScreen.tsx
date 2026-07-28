import React, { useState } from "react";
import { Alert, Text, StyleSheet, View } from "react-native";
import { useFocusEffect } from "../useFocus";
import { myReport, type MyReport, type ReportPeriod } from "../api";
import { Btn, Card, Chip, Field, Label, Screen, Sub, TopBar } from "../components/ui";
import { colors } from "../theme";

const PERIODS: { label: string; days?: number }[] = [
  { label: "all" },
  { label: "7d", days: 7 },
  { label: "30d", days: 30 },
  { label: "90d", days: 90 },
];

export function MyReportScreen({ onBack }: { onBack: () => void }) {
  const [report, setReport] = useState<MyReport | null>(null);
  const [days, setDays] = useState<number | undefined>(undefined);
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");
  const [custom, setCustom] = useState(false);
  const [loadError, setLoadError] = useState("");

  const period = (): ReportPeriod | undefined => {
    if (custom && (dateFrom.trim() || dateTo.trim())) {
      return { date_from: dateFrom.trim() || undefined, date_to: dateTo.trim() || undefined };
    }
    return days != null ? { days } : undefined;
  };

  const reload = async () => {
    try {
      if (custom) {
        const from = dateFrom.trim();
        const to = dateTo.trim();
        if (from && !/^\d{4}-\d{2}-\d{2}$/.test(from)) {
          setLoadError("From date must be YYYY-MM-DD");
          return;
        }
        if (to && !/^\d{4}-\d{2}-\d{2}$/.test(to)) {
          setLoadError("To date must be YYYY-MM-DD");
          return;
        }
      }
      setLoadError("");
      setReport(await myReport(period()));
    } catch (e) {
      setLoadError(e instanceof Error ? e.message : "Failed");
      Alert.alert("Fos", e instanceof Error ? e.message : "Failed");
    }
  };

  useFocusEffect(reload);
  React.useEffect(() => {
    void reload();
  }, [days, custom, dateFrom, dateTo]);

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
    <Screen scroll>
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
          <Field autoCapitalize="none" value={dateFrom} onChangeText={setDateFrom} placeholder="optional" />
          <Label>To (YYYY-MM-DD)</Label>
          <Field autoCapitalize="none" value={dateTo} onChangeText={setDateTo} placeholder="optional" />
        </>
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
