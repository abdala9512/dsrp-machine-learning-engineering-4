export type ImdbTitle = {
  id?: string;
  title?: string;
  url?: string | null;
  year?: number | null;
  image?: string | null;
  rating?: number | null;
  ratingVotes?: number | null;
  type?: string | null;
};

export type ImdbSearchResponse = {
  titles?: ImdbTitle[];
  results?: ImdbTitle[];
  items?: ImdbTitle[];
  data?: ImdbTitle[] | { titles?: ImdbTitle[] };
  total?: number;
};
