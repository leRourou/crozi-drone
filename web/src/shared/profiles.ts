/**
 * Téléphones de l'équipe, importés au build depuis le contrat partagé contracts/profiles.json
 * (seule source ; le serveur valide la même liste au démarrage). Partagé par toutes les pages.
 */
import contract from "@contracts/profiles.json";

export interface Profile {
  /** Identifiant ASCII stable, envoyé dans hello.profile. */
  readonly id: string;
  readonly label: string;
  /** Position du téléphone en mètres, repère local du terrain (x ; y ; z, z = hauteur). */
  readonly position_m: { readonly x: number; readonly y: number; readonly z: number };
}

export type ProfileId = Profile["id"];

/** Ordre d'affichage = ordre du contrat. La forme du JSON est vérifiée ici par le compilateur. */
export const PROFILES: readonly Profile[] = contract.profiles;

/** Valeur brute d'un <select> → profil, ou undefined (option vide, valeur inconnue). */
export function findProfile(value: string): Profile | undefined {
  return PROFILES.find((p) => p.id === value);
}
