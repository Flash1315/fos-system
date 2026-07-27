import React, { useState } from "react";
import { Alert, Text, StyleSheet } from "react-native";
import { useFocusEffect } from "../useFocus";
import { orgReport, type OrgReport } from "../api";
import { Card, Label, Screen, Sub, TopBar } from "../components/ui";
import { colors } from "../theme";

export function ReportsScreen({ onBack }: { onBack: () => void }) {
  const [report, setReport] = useState<OrgReport | null>(null);

  useFocusEffect(async () => {
    try {
      setReport(await orgReport());
    } catch (e) {
      Alert.alert("Fos", e instanceof Error ? e.message : "Failed");
    }
  });

  return (
    <Screen scroll>
      <TopBar onBack={onBack} onCancel={onBack} />
      <Text style={styles.title}>Org report</Text>
      {!report ? (
        <Sub>Loading…</Sub>
      ) : (
        <>
          <Card>
            <Label>Cash position</Label>
            <Text style={styles.big}>
              {report.cash_position.toLocaleString()} {report.currency}
            </Text>
            <Sub>{report.pending_count} pending · {report.team_count} active teammates</Sub>
          </Card>
          <Card>
            <Label>Approved totals</Label>
            <Text style={styles.line}>Expense: {report.approved_expense_total.toLocaleString()}</Text>
            <Text style={styles.line}>Fuel: {report.approved_fuel_total.toLocaleString()}</Text>
            <Text style={styles.line}>Income cash: {report.approved_income_cash.toLocaleString()}</Text>
            <Text style={styles.line}>Income transfer: {report.approved_income_transfer.toLocaleString()}</Text>
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
        </>
      )}
    </Screen>
  );
}

const styles = StyleSheet.create({
  title: { color: colors.text, fontSize: 26, fontWeight: "700", marginVertical: 8 },
  big: { color: colors.text, fontSize: 24, fontWeight: "700" },
  line: { color: colors.text, marginTop: 6 },
});
