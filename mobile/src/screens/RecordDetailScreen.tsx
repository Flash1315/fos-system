import React, { useState } from "react";
import { Alert, Image, Text, StyleSheet } from "react-native";
import { useFocusEffect } from "../useFocus";
import {
  cancelRecord,
  commentRecord,
  decideRecord,
  getRecord,
  mediaUrl,
  updateRecord,
  type MoneyRecord,
  type User,
} from "../api";
import { NoteModal } from "../components/NoteModal";
import { Btn, Card, Field, Label, Row, Screen, Sub, TopBar } from "../components/ui";
import { formatMoney, formatWhen, statusColor } from "../format";
import { colors } from "../theme";

export function RecordDetailScreen({
  id,
  user,
  busy,
  setBusy,
  onBack,
}: {
  id: number;
  user: User;
  busy: boolean;
  setBusy: (v: boolean) => void;
  onBack: () => void;
}) {
  const [rec, setRec] = useState<MoneyRecord | null>(null);
  const [rejectOpen, setRejectOpen] = useState(false);
  const [commentOpen, setCommentOpen] = useState(false);
  const [editing, setEditing] = useState(false);
  const [editAmount, setEditAmount] = useState("");
  const [editPlace, setEditPlace] = useState("");
  const [editComment, setEditComment] = useState("");
  const isManager = user.role === "owner" || user.role === "manager";

  const reload = async () => {
    try {
      const row = await getRecord(id);
      setRec(row);
      setEditAmount(String(row.amount));
      setEditPlace(row.place || "");
      setEditComment(row.comment || "");
    } catch (e) {
      Alert.alert("Fos", e instanceof Error ? e.message : "Failed");
    }
  };

  useFocusEffect(reload);

  const decide = async (approve: boolean, note = "") => {
    setBusy(true);
    try {
      setRec(await decideRecord(id, approve, note));
    } catch (e) {
      Alert.alert("Fos", e instanceof Error ? e.message : "Failed");
    } finally {
      setBusy(false);
    }
  };

  const onCancel = async () => {
    setBusy(true);
    try {
      setRec(await cancelRecord(id));
      Alert.alert("Fos", "Record cancelled");
    } catch (e) {
      Alert.alert("Fos", e instanceof Error ? e.message : "Failed");
    } finally {
      setBusy(false);
    }
  };

  const onComment = async (note: string) => {
    setBusy(true);
    try {
      setRec(await commentRecord(id, note));
    } catch (e) {
      Alert.alert("Fos", e instanceof Error ? e.message : "Failed");
    } finally {
      setBusy(false);
    }
  };

  const onSaveEdit = async () => {
    const value = Number(editAmount.replace(",", "."));
    if (!value || value <= 0) {
      Alert.alert("Fos", "Enter a valid amount");
      return;
    }
    setBusy(true);
    try {
      const updated = await updateRecord(id, {
        amount: value,
        place: editPlace,
        comment: editComment,
      });
      setRec(updated);
      setEditing(false);
    } catch (e) {
      Alert.alert("Fos", e instanceof Error ? e.message : "Failed");
    } finally {
      setBusy(false);
    }
  };

  const canCancel =
    !!rec &&
    rec.status === "pending" &&
    (rec.created_by === user.id || isManager);
  const canEdit =
    !!rec &&
    rec.status === "pending" &&
    (rec.created_by === user.id || isManager);

  return (
    <Screen scroll>
      <TopBar onBack={onBack} onCancel={onBack} />
      <Text style={styles.title}>Record #{id}</Text>
      {!rec ? (
        <Sub>Loading…</Sub>
      ) : (
        <>
          <Card>
            <Label>Kind / status</Label>
            <Text style={styles.line}>
              {rec.kind} · <Text style={{ color: statusColor(rec.status) }}>{rec.status}</Text>
            </Text>
            <Label>Amount</Label>
            <Text style={styles.big}>{formatMoney(rec.amount, rec.currency)}</Text>
            <Label>Purpose</Label>
            <Text style={styles.line}>{rec.purpose || "—"}</Text>
            <Label>Category</Label>
            <Text style={styles.line}>{rec.category || "—"}</Text>
            <Label>Place</Label>
            <Text style={styles.line}>{rec.place || "—"}</Text>
            {!!rec.bike && (
              <>
                <Label>Bike</Label>
                <Text style={styles.line}>{rec.bike}</Text>
              </>
            )}
            {!!rec.payment_source && (
              <>
                <Label>Payment source</Label>
                <Text style={styles.line}>
                  {rec.payment_source === "my_pocket" ? "My pocket" : "Cash on hand"}
                </Text>
              </>
            )}
            <Label>By</Label>
            <Text style={styles.line}>
              {rec.created_by_name || rec.created_by} · {formatWhen(rec.created_at)}
            </Text>
            {!!rec.occurred_at && (
              <>
                <Label>Occurred</Label>
                <Text style={styles.line}>{formatWhen(rec.occurred_at)}</Text>
              </>
            )}
            {!!rec.client_name && (
              <>
                <Label>Client</Label>
                <Text style={styles.line}>
                  {rec.client_name} · {rec.payment_method || "—"}
                </Text>
              </>
            )}
            {(rec.liters != null || rec.odometer != null) && (
              <>
                <Label>Fuel</Label>
                <Text style={styles.line}>
                  {rec.liters ?? "—"} L · odo {rec.odometer ?? "—"}
                </Text>
              </>
            )}
            <Label>Comment</Label>
            <Text style={styles.line}>{rec.comment || "—"}</Text>
            {!!rec.decided_at && (
              <>
                <Label>Decided</Label>
                <Text style={styles.line}>{formatWhen(rec.decided_at)}</Text>
              </>
            )}
          </Card>
          {!!rec.photo_url && (
            <Card>
              <Label>Receipt</Label>
              <Image source={{ uri: mediaUrl(rec.photo_url) }} style={styles.photo} />
            </Card>
          )}
          {isManager && rec.status === "pending" && (
            <Row>
              <Btn title="Approve" disabled={busy} onPress={() => decide(true)} />
              <Btn title="Reject" variant="danger" disabled={busy} onPress={() => setRejectOpen(true)} />
            </Row>
          )}
          {canEdit && !editing && (
            <Btn title="Edit pending" variant="ghost" disabled={busy} onPress={() => setEditing(true)} />
          )}
          {canEdit && editing && (
            <Card>
              <Label>Edit amount</Label>
              <Field keyboardType="decimal-pad" value={editAmount} onChangeText={setEditAmount} />
              <Label>Place</Label>
              <Field value={editPlace} onChangeText={setEditPlace} />
              <Label>Comment</Label>
              <Field value={editComment} onChangeText={setEditComment} />
              <Row>
                <Btn title="Save" disabled={busy} onPress={onSaveEdit} />
                <Btn title="Cancel edit" variant="ghost" onPress={() => setEditing(false)} />
              </Row>
            </Card>
          )}
          {canCancel && (
            <Btn title="Cancel record" variant="ghost" disabled={busy} onPress={onCancel} />
          )}
          {isManager && (
            <Btn
              title="Add manager note"
              variant="ghost"
              disabled={busy}
              onPress={() => setCommentOpen(true)}
            />
          )}
        </>
      )}
      <NoteModal
        visible={rejectOpen}
        title="Reject record"
        onCancel={() => setRejectOpen(false)}
        onSubmit={async (note) => {
          setRejectOpen(false);
          await decide(false, note);
        }}
      />
      <NoteModal
        visible={commentOpen}
        title="Manager note"
        onCancel={() => setCommentOpen(false)}
        onSubmit={async (note) => {
          setCommentOpen(false);
          await onComment(note);
        }}
      />
    </Screen>
  );
}

const styles = StyleSheet.create({
  title: { color: colors.text, fontSize: 26, fontWeight: "700", marginVertical: 8 },
  line: { color: colors.text, marginTop: 2 },
  big: { color: colors.text, fontSize: 22, fontWeight: "700" },
  photo: { width: "100%", height: 220, borderRadius: 12, marginTop: 8, backgroundColor: colors.cardAlt },
});
