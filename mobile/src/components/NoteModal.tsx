import React, { useEffect, useRef, useState } from "react";
import { Modal, Pressable, StyleSheet, Text, View } from "react-native";
import { colors } from "../theme";
import { Btn, Field, Label } from "./ui";

/** Cross-platform note prompt (Alert.prompt is iOS-only). */
export function NoteModal({
  visible,
  title,
  onCancel,
  onSubmit,
  required = false,
  label,
  placeholder = "Reason",
  secureTextEntry = false,
  confirmField = false,
  confirmLabel = "Confirm",
  confirmPlaceholder = "repeat",
  minLength,
  maxLength,
  confirmTitle = "Confirm",
  confirmVariant = "primary",
}: {
  visible: boolean;
  title: string;
  onCancel: () => void;
  onSubmit: (note: string) => void | Promise<void>;
  required?: boolean;
  label?: string;
  placeholder?: string;
  secureTextEntry?: boolean;
  confirmField?: boolean;
  confirmLabel?: string;
  confirmPlaceholder?: string;
  /** When required, minimum trimmed length (default 2; use 6 for passwords). */
  minLength?: number;
  maxLength?: number;
  confirmTitle?: string;
  confirmVariant?: "primary" | "secondary" | "danger" | "ghost";
}) {
  const [note, setNote] = useState("");
  const [confirm, setConfirm] = useState("");
  const [error, setError] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const submitLock = useRef(false);
  const min = minLength ?? (required ? 2 : 0);

  useEffect(() => {
    if (!visible) {
      setNote("");
      setConfirm("");
      setError("");
      setSubmitting(false);
      submitLock.current = false;
    }
  }, [visible]);

  return (
    <Modal visible={visible} transparent animationType="fade" onRequestClose={onCancel}>
      <Pressable style={styles.backdrop} onPress={onCancel}>
        <Pressable style={styles.sheet} onPress={(e) => e.stopPropagation()}>
          <Text style={styles.title}>{title}</Text>
          <Label>{label || (required ? "Note (required)" : "Note (optional)")}</Label>
          <Field
            value={note}
            onChangeText={(t) => {
              setNote(t);
              setError("");
            }}
            placeholder={placeholder}
            secureTextEntry={secureTextEntry}
            autoCapitalize={secureTextEntry ? "none" : undefined}
            autoCorrect={!secureTextEntry}
            editable={!submitting}
          />
          {confirmField && (
            <>
              <Label>{confirmLabel}</Label>
              <Field
                value={confirm}
                onChangeText={(t) => {
                  setConfirm(t);
                  setError("");
                }}
                placeholder={confirmPlaceholder}
                secureTextEntry={secureTextEntry}
                autoCapitalize={secureTextEntry ? "none" : undefined}
                autoCorrect={!secureTextEntry}
                editable={!submitting}
              />
            </>
          )}
          {!!error && <Text style={styles.error}>{error}</Text>}
          <View style={styles.row}>
            <Btn title="Cancel" variant="ghost" onPress={onCancel} disabled={submitting} />
            <Btn
              title={submitting ? "…" : confirmTitle}
              variant={confirmVariant}
              disabled={submitting}
              onPress={() => {
                if (submitLock.current) return;
                const trimmed = secureTextEntry ? note : note.trim();
                const confirmTrimmed = secureTextEntry ? confirm : confirm.trim();
                if (required && trimmed.length < min) {
                  setError(
                    secureTextEntry
                      ? `Must be at least ${min} characters`
                      : `Add a short reason (min ${min} characters)`,
                  );
                  return;
                }
                if (maxLength != null && trimmed.length > maxLength) {
                  setError(`Must be at most ${maxLength} characters`);
                  return;
                }
                if (confirmField && trimmed !== confirmTrimmed) {
                  setError("Entries do not match");
                  return;
                }
                submitLock.current = true;
                setSubmitting(true);
                Promise.resolve(onSubmit(trimmed))
                  .catch(() => {
                    /* caller shows errors */
                  })
                  .finally(() => {
                    submitLock.current = false;
                    setSubmitting(false);
                    setNote("");
                    setConfirm("");
                    setError("");
                  });
              }}
            />
          </View>
        </Pressable>
      </Pressable>
    </Modal>
  );
}

const styles = StyleSheet.create({
  backdrop: {
    flex: 1,
    backgroundColor: "rgba(0,0,0,0.55)",
    justifyContent: "center",
    padding: 24,
  },
  sheet: {
    backgroundColor: colors.card,
    borderRadius: 16,
    padding: 16,
  },
  title: { color: colors.text, fontSize: 18, fontWeight: "700", marginBottom: 8 },
  row: { flexDirection: "row", gap: 10, marginTop: 14, justifyContent: "flex-end" },
  error: { color: colors.danger, marginTop: 6 },
});
